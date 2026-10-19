// Live mode: the bridge attaches to a SOLIDWORKS session the person started, for the
// modeling assistant (docs/ASSISTANT.md, "Attaching to a live session").
//
// It binds the session asked for, by process id, only through the Running Object Table
// moniker "SolidWorks_PID_<pid>" (never GetActiveObject), and never ends that process,
// closes or saves one of its documents, or changes a SOLIDWORKS option or user
// preference. (The opt-in tests' --test-session operations, TestSession.cs, close the
// documents they created or opened there, and only those.) What it changes, only in the document the app names:
// - a safety copy of a part, written with IModelDocExtension.SaveAs3 and
//   swSaveAsOptions_Copy, only as checkpoint-<run id>.sldprt in a run folder under
//   %LOCALAPPDATA%\SolidSeas\runs; the copy leaves the open document, its path, its saved
//   state and its undo list alone (answer 1);
// - one named undo entry around an approved script (answer 4). Opening it is recorded in a
//   state file first, so that a bridge started after one that was ended mid-script closes
//   the entry it left open;
// - the vocabulary's operations, on the active part only; and, as an inverse, the deletion
//   of a feature this bridge made, selected by its persist reference, with
//   swDelete_Absorbed so an extrude's sketch goes with it (answer 6).
// Entities are named by persist references (GetPersistReference3), sent as base64; a
// dimension by its feature's reference and its own name ("D1"), from which this code
// builds the name SOLIDWORKS resolves ("D1@Sketch2"), so no other document can be named.
// A profile arrives in the frame the snapshot reports for each plane and planar face (an
// origin, an x direction and the normal) and goes into the sketch through that sketch's
// own ModelToSketchTransform, so it lands where the model was told, whatever axes
// SOLIDWORKS gives the sketch.
//
// A SOLIDWORKS a bridge started for batch work carries a named object while it runs
// (Local\SolidSeas-Batch-<pid>), which the session list reports, so the app can leave it
// out of the sessions it offers.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Threading;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace SolidSeas.SwBridge
{
    static class LiveNative
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
        [DllImport("advapi32.dll", SetLastError = true)]
        static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
        [DllImport("advapi32.dll", SetLastError = true)]
        static extern bool GetTokenInformation(IntPtr token, int infoClass, out int value, int length, out int returned);

        const uint ProcessQueryLimitedInformation = 0x1000;
        const uint TokenQuery = 0x0008;
        const int TokenElevation = 20;

        // Whether the process runs elevated; null when that cannot be read.
        public static bool? Elevated(int pid)
        {
            IntPtr process = OpenProcess(ProcessQueryLimitedInformation, false, pid);
            if (process == IntPtr.Zero) return null;
            try
            {
                IntPtr token;
                if (!OpenProcessToken(process, TokenQuery, out token)) return null;
                try
                {
                    int elevated, returned;
                    if (!GetTokenInformation(token, TokenElevation, out elevated, 4, out returned)) return null;
                    return elevated != 0;
                }
                finally
                {
                    Native.CloseHandle(token);
                }
            }
            finally
            {
                Native.CloseHandle(process);
            }
        }
    }

    static partial class Operations
    {
        static ISldWorks live;
        static int livePid;
        // Features this bridge made in the attached session, by persist reference: the only
        // ones live_delete_feature deletes.
        static readonly HashSet<string> madeHere = new HashSet<string>();
        // Custom properties this bridge set, by document, configuration and name: the only ones
        // live_restore_property puts back.
        static readonly HashSet<string> propertiesSetHere = new HashSet<string>();
        static readonly Regex UndoName = new Regex(@"\ASolidSeas (script|step [0-9]{1,3}: [a-z_]{1,32}|revert of step [0-9]{1,3})\z");
        static Mutex batchMarker;
        const string BatchMarkerPrefix = @"Local\SolidSeas-Batch-";
        const string WriterPrefix = @"Local\SolidSeas-Live-";
        const string ScriptUndoName = "SolidSeas script";
        const int DefaultEntityLimit = 5000;
        const double OnPlane = 1e-7; // metres: how far a profile point may lie off its sketch's plane
        static readonly Regex CheckpointName = new Regex(@"\Acheckpoint-[A-Za-z0-9-]{1,64}\.sldprt\z", RegexOptions.IgnoreCase);
        static readonly string[] ProtectedProperties = { "partno", "partnumber", "number", "revision", "rev" };

        static void RegisterLive(Dictionary<string, Handler> handlers)
        {
            handlers["list_sessions"] = ListSessions;
            handlers["live_attach"] = LiveAttach;
            handlers["live_detach"] = LiveDetach;
            handlers["live_documents"] = LiveDocuments;
            handlers["live_document_info"] = LiveDocumentInfo;
            handlers["live_snapshot"] = LiveSnapshot;
            handlers["live_features"] = LiveFeatures;
            handlers["live_dimensions"] = LiveDimensions;
            handlers["live_properties"] = LiveProperties;
            handlers["live_mass_properties"] = LiveMassProperties;
            handlers["live_checkpoint"] = LiveCheckpoint;
            handlers["live_begin_undo"] = LiveBeginUndo;
            handlers["live_end_undo"] = LiveEndUndo;
            handlers["live_operation"] = LiveOperation;
            handlers["live_delete_feature"] = LiveDeleteFeature;
            handlers["live_restore_property"] = LiveRestoreProperty;
            handlers["live_current_refs"] = LiveCurrentRefs;
        }

        // ------------------------------------------------------------------ batch marker
        static void MarkBatch(int pid)
        {
            UnmarkBatch();
            batchMarker = new Mutex(false, BatchMarkerPrefix + pid);
        }

        static void UnmarkBatch()
        {
            if (batchMarker == null) return;
            batchMarker.Dispose();
            batchMarker = null;
        }

        static bool NamedObjectExists(string name)
        {
            Mutex m;
            try
            {
                if (!Mutex.TryOpenExisting(name, out m)) return false;
            }
            catch (UnauthorizedAccessException)
            {
                return true; // there, and not ours to open
            }
            m.Dispose();
            return true;
        }

        // ------------------------------------------------------------------ sessions
        static Dictionary<string, object> ListSessions(Args args)
        {
            args.Allow("pids");
            HashSet<int> only = null;
            if (args.Has("pids"))
            {
                only = new HashSet<int>();
                foreach (object o in args.List("pids")) only.Add(Args.WholeNumber(o, "pids"));
            }
            int windowsSession;
            using (Process me = Process.GetCurrentProcess()) windowsSession = me.SessionId;
            List<object> sessions = new List<object>();
            Process[] found = Process.GetProcessesByName("SLDWORKS");
            try
            {
                foreach (Process p in found)
                {
                    int pid, theirs;
                    try
                    {
                        pid = p.Id;
                        theirs = p.SessionId;
                    }
                    catch (Exception)
                    {
                        continue; // ended while listed
                    }
                    if (theirs != windowsSession || (only != null && !only.Contains(pid))) continue;
                    sessions.Add(LiveSession(pid));
                }
            }
            finally
            {
                foreach (Process p in found) p.Dispose();
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["sessions"] = sessions;
            d["attached"] = live != null ? (object)livePid : null;
            return d;
        }

        static Dictionary<string, object> LiveSession(int pid)
        {
            Dictionary<string, object> s = new Dictionary<string, object>();
            s["pid"] = pid;
            s["solidseas"] = NamedObjectExists(BatchMarkerPrefix + pid);
            s["writer"] = NamedObjectExists(WriterPrefix + pid);
            bool attached = live != null && livePid == pid;
            s["attached"] = attached;
            bool? theirs = LiveNative.Elevated(pid);
            bool? ours;
            using (Process me = Process.GetCurrentProcess()) ours = LiveNative.Elevated(me.Id);
            if (theirs == true && ours != true)
            {
                s["reachable"] = false;
                s["note"] = "administrator";
                return s;
            }
            ISldWorks app = attached ? live : Rot.Find(pid) as ISldWorks;
            if (app == null)
            {
                s["reachable"] = false;
                s["note"] = theirs == null ? "not_registered_or_administrator" : "not_registered";
                return s;
            }
            try
            {
                s["revision"] = app.RevisionNumber();
                s["documents"] = LiveDocumentList(app);
                s["reachable"] = true;
            }
            catch (COMException e)
            {
                s["reachable"] = false;
                s["note"] = Classify(e.ErrorCode);
            }
            finally
            {
                if (!attached)
                {
                    try { Marshal.FinalReleaseComObject(app); }
                    catch (Exception) { }
                }
            }
            return s;
        }

        static List<object> LiveDocumentList(ISldWorks app)
        {
            List<object> list = new List<object>();
            ModelDoc2 active = app.ActiveDoc as ModelDoc2;
            object[] open = app.GetDocuments() as object[];
            if (open == null) return list;
            foreach (object o in open)
            {
                ModelDoc2 doc = o as ModelDoc2;
                if (doc == null) continue;
                Dictionary<string, object> d = new Dictionary<string, object>();
                string path = doc.GetPathName() ?? "";
                d["key"] = path.Length == 0 ? doc.GetTitle() : path;
                d["title"] = doc.GetTitle();
                d["path"] = path;
                d["type"] = TypeName(doc.GetType());
                d["visible"] = doc.Visible;
                d["active"] = active != null && ReferenceEquals(doc, active);
                d["dirty"] = doc.GetSaveFlag();
                list.Add(d);
            }
            return list;
        }

        static Dictionary<string, object> LiveAttach(Args args)
        {
            args.Allow("pid");
            int pid = args.Int("pid", 0, 1, int.MaxValue);
            if (process != null && !process.HasExited && process.Id == pid)
                throw new BridgeException("refused", "this bridge started that SOLIDWORKS for batch work; live mode attaches to another one");
            if (live == null || livePid != pid)
            {
                DetachLive();
                CheckSolidWorksProcess(pid);
                ISldWorks app = Rot.Find(pid) as ISldWorks;
                if (app == null)
                    throw new BridgeException("not_found", "SolidWorks_PID_" + pid + " is not in the Running Object Table: SOLIDWORKS is still starting, has ended, or runs as administrator");
                live = app;
                livePid = pid;
            }
            Dictionary<string, object> d = LiveSession(pid);
            // An undo entry or a lock that an ended bridge left is undone, unless a writer holds the session now.
            bool free = !NamedObjectExists(WriterPrefix + pid);
            d["undo_entry_closed"] = free && CloseLeftUndoEntry(pid);
            d["lock_released"] = free && ReleaseLeftLock(pid);
            return d;
        }

        static void CheckSolidWorksProcess(int pid)
        {
            Process p;
            try
            {
                p = Process.GetProcessById(pid);
            }
            catch (ArgumentException)
            {
                throw new BridgeException("not_found", "no process " + pid + " is running");
            }
            using (p)
            {
                using (Process me = Process.GetCurrentProcess())
                {
                    if (!string.Equals(p.ProcessName, "SLDWORKS", StringComparison.OrdinalIgnoreCase) || p.SessionId != me.SessionId)
                        throw new BridgeException("refused", "process " + pid + " is not a SOLIDWORKS in this Windows session");
                }
            }
        }

        // Lets go of the attached session: the script's undo entry, if this bridge left one
        // open, is closed, and nothing in SOLIDWORKS is ended, closed or saved.
        public static void DetachLive()
        {
            if (live == null) return;
            CloseTestDocuments();
            try
            {
                if (!NamedObjectExists(WriterPrefix + livePid))
                {
                    CloseLeftUndoEntry(livePid);
                    ReleaseLeftLock(livePid);
                }
            }
            catch (Exception e)
            {
                Console.Error.WriteLine("closing the script's undo entry: " + e.Message);
            }
            try { Marshal.FinalReleaseComObject(live); }
            catch (Exception) { }
            live = null;
            livePid = 0;
            madeHere.Clear();
            propertiesSetHere.Clear();
        }

        static Dictionary<string, object> LiveDetach(Args args)
        {
            args.Allow();
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["was_attached"] = live != null ? (object)livePid : null;
            DetachLive();
            return d;
        }

        static ISldWorks RequireLive()
        {
            if (live == null) throw new BridgeException("not_attached", "live_attach first");
            return live;
        }

        static Dictionary<string, object> LiveDocuments(Args args)
        {
            args.Allow();
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["pid"] = livePid;
            d["documents"] = LiveDocumentList(RequireLive());
            return d;
        }

        // The open document a key names: its full path, or its title while it has never been saved.
        static ModelDoc2 FindLive(string key)
        {
            object[] open = RequireLive().GetDocuments() as object[];
            if (open == null) return null;
            foreach (object o in open)
            {
                ModelDoc2 doc = o as ModelDoc2;
                if (doc == null) continue;
                string path = doc.GetPathName() ?? "";
                bool match = path.Length == 0
                    ? string.Equals(doc.GetTitle(), key, StringComparison.Ordinal)
                    : string.Equals(path, key, StringComparison.OrdinalIgnoreCase);
                if (match) return doc;
            }
            return null;
        }

        static ModelDoc2 LiveDoc(Args args, out string key)
        {
            RequireLive();
            key = args.String("document", null);
            if (string.IsNullOrEmpty(key)) throw new BridgeException("invalid_argument", "document is required");
            ModelDoc2 doc = FindLive(key);
            if (doc == null) throw new BridgeException("not_found", "the document is no longer open in this SOLIDWORKS session");
            return doc;
        }

        static ModelDoc2 LivePart(Args args, out string key)
        {
            ModelDoc2 doc = LiveDoc(args, out key);
            if (doc.GetType() != (int)swDocumentTypes_e.swDocPART)
                throw new BridgeException("not_a_part", "this works on a part; the document is " + TypeName(doc.GetType()) + " in SOLIDWORKS");
            return doc;
        }

        static bool IsActive(ModelDoc2 doc)
        {
            ModelDoc2 active = live.ActiveDoc as ModelDoc2;
            return active != null && ReferenceEquals(active, doc);
        }

        static Configuration ActiveConfiguration(ModelDoc2 doc)
        {
            ConfigurationManager m = doc.ConfigurationManager;
            return m == null ? null : m.ActiveConfiguration;
        }

        static Dictionary<string, object> LiveDescribe(ModelDoc2 doc, string key)
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["title"] = doc.GetTitle();
            d["type"] = TypeName(doc.GetType());
            d["dirty"] = doc.GetSaveFlag();
            d["read_only"] = doc.IsOpenedReadOnly();
            Configuration active = ActiveConfiguration(doc);
            d["active_configuration"] = active == null ? null : active.Name;
            string[] names = doc.GetConfigurationNames() as string[];
            d["configurations"] = names ?? new string[0];
            d["feature_count"] = doc.GetFeatureCount();
            d["active"] = IsActive(doc);
            SketchManager sketches = doc.SketchManager;
            d["editing_sketch"] = sketches != null && sketches.ActiveSketch != null;
            return d;
        }

        static Dictionary<string, object> LiveDocumentInfo(Args args)
        {
            args.Allow("document");
            string key;
            ModelDoc2 doc = LiveDoc(args, out key);
            return LiveDescribe(doc, key);
        }

        // ------------------------------------------------------------------ reading
        static object Finite(double x)
        {
            return double.IsNaN(x) || double.IsInfinity(x) ? null : (object)x;
        }

        static List<object> Vec(double[] a, int at)
        {
            if (a == null || a.Length < at + 3) return null;
            for (int i = at; i < at + 3; i++)
            {
                if (double.IsNaN(a[i]) || double.IsInfinity(a[i])) return null;
            }
            return new List<object> { a[at], a[at + 1], a[at + 2] };
        }

        static double[] Unit(double x, double y, double z)
        {
            double n = Math.Sqrt(x * x + y * y + z * z);
            if (!(n > 1e-12) || double.IsInfinity(n)) return null;
            return new double[] { x / n, y / n, z / n };
        }

        static double Dot(double[] a, double[] b)
        {
            return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
        }

        static string RefOf(ModelDoc2 doc, object entity)
        {
            if (entity == null) return null;
            try
            {
                byte[] bytes = doc.Extension.GetPersistReference3(entity) as byte[];
                return bytes == null || bytes.Length == 0 ? null : Convert.ToBase64String(bytes);
            }
            catch (COMException)
            {
                return null;
            }
        }

        // The entity a persist reference names, or a refusal saying why there is none.
        static object Resolve(ModelDoc2 doc, string reference, string what, bool suppressedToo)
        {
            byte[] bytes;
            try
            {
                bytes = Convert.FromBase64String(reference ?? "");
            }
            catch (FormatException)
            {
                throw new BridgeException("invalid_argument", what + " is not a persist reference");
            }
            if (bytes.Length == 0) throw new BridgeException("invalid_argument", what + " is not a persist reference");
            int state;
            object found = doc.Extension.GetObjectByPersistReference3(bytes, out state);
            bool usable = state == (int)swPersistReferencedObjectStates_e.swPersistReferencedObject_Ok
                || (suppressedToo && state == (int)swPersistReferencedObjectStates_e.swPersistReferencedObject_Suppressed);
            if (found == null || !usable)
            {
                string why = state == (int)swPersistReferencedObjectStates_e.swPersistReferencedObject_Deleted ? "it was deleted"
                    : state == (int)swPersistReferencedObjectStates_e.swPersistReferencedObject_Suppressed ? "it is suppressed"
                    : "it no longer resolves";
                throw new BridgeException("not_found", what + " names nothing in the part now: " + why);
            }
            return found;
        }

        static bool Suppressed(Feature feature)
        {
            bool[] states = feature.IsSuppressed2((int)swInConfigurationOpts_e.swThisConfiguration, null) as bool[];
            return states != null && states.Length > 0 && states[0];
        }

        // Feature tree entries that are folders, not geometry: several share one persist
        // reference (answer 6), so they get no handle.
        static bool FolderType(string type)
        {
            return type == null || type.EndsWith("Folder", StringComparison.Ordinal) || type == "DetailCabinet"
                || type == "OriginProfileFeature";
        }

        static List<KeyValuePair<Dimension, int>> FeatureDimensions(Feature feature)
        {
            List<KeyValuePair<Dimension, int>> list = new List<KeyValuePair<Dimension, int>>();
            object display = feature.GetFirstDisplayDimension();
            while (display != null && list.Count < 10000)
            {
                DisplayDimension dd = display as DisplayDimension;
                if (dd != null)
                {
                    Dimension dim = dd.GetDimension2(0);
                    if (dim != null) list.Add(new KeyValuePair<Dimension, int>(dim, dd.Type2));
                }
                display = feature.GetNextDisplayDimension(display);
            }
            return list;
        }

        static string DimensionKind(int type)
        {
            switch (type)
            {
                case (int)swDimensionType_e.swAngularDimension:
                case (int)swDimensionType_e.swAngularOrdinateDimension:
                    return "angular";
                case (int)swDimensionType_e.swRadialDimension:
                    return "radial";
                case (int)swDimensionType_e.swDiameterDimension:
                    return "diameter";
                case (int)swDimensionType_e.swScalarDimension:
                    return null; // a count or a ratio, not a length
                default:
                    return "linear";
            }
        }

        static object DimensionValue(Dimension dim)
        {
            double[] v = dim.GetSystemValue3((int)swInConfigurationOpts_e.swThisConfiguration, null) as double[];
            return v == null || v.Length == 0 ? null : Finite(v[0]);
        }

        static string LengthUnit(ModelDoc2 doc)
        {
            int unit = doc.Extension.GetUserPreferenceInteger((int)swUserPreferenceIntegerValue_e.swUnitsLinear,
                                                              (int)swUserPreferenceOption_e.swDetailingNoOptionSpecified);
            switch (unit)
            {
                case (int)swLengthUnit_e.swMM: return "mm";
                case (int)swLengthUnit_e.swCM: return "cm";
                case (int)swLengthUnit_e.swMETER: return "m";
                case (int)swLengthUnit_e.swINCHES: return "in";
                case (int)swLengthUnit_e.swFEET:
                case (int)swLengthUnit_e.swFEETINCHES: return "ft";
                default: return "other";
            }
        }

        // A reference plane's frame: origin, x direction and normal, nine numbers, from the
        // plane's own transform (rows: x, y, z; then the origin).
        static double[] PlaneFrame(Feature feature)
        {
            RefPlane plane = feature.GetSpecificFeature2() as RefPlane;
            MathTransform t = plane == null ? null : plane.Transform;
            double[] m = t == null ? null : t.ArrayData as double[];
            if (m == null || m.Length < 12) return null;
            double[] x = Unit(m[0], m[1], m[2]);
            double[] n = Unit(m[6], m[7], m[8]);
            if (x == null || n == null) return null;
            return new double[] { m[9], m[10], m[11], x[0], x[1], x[2], n[0], n[1], n[2] };
        }

        // A planar face's frame. The normal points out of the material; the origin is the foot
        // of the model origin on the face's plane; x is the first of the model's X, Y and Z axes
        // that is not nearly along the normal, made perpendicular to it.
        static double[] FaceFrame(Face2 face)
        {
            Surface s = face.GetSurface() as Surface;
            if (s == null || !s.IsPlane()) return null;
            double[] n = face.Normal as double[];
            double[] p = s.PlaneParams as double[];
            if (n == null || n.Length < 3 || p == null || p.Length < 6) return null;
            double[] normal = Unit(n[0], n[1], n[2]);
            if (normal == null) return null;
            double along = normal[0] * p[3] + normal[1] * p[4] + normal[2] * p[5];
            double[][] axes = { new double[] { 1, 0, 0 }, new double[] { 0, 1, 0 }, new double[] { 0, 0, 1 } };
            foreach (double[] a in axes)
            {
                double c = Dot(a, normal);
                if (Math.Abs(c) > 0.9) continue;
                double[] x = Unit(a[0] - c * normal[0], a[1] - c * normal[1], a[2] - c * normal[2]);
                if (x == null) continue;
                return new double[] {
                    normal[0] * along, normal[1] * along, normal[2] * along,
                    x[0], x[1], x[2], normal[0], normal[1], normal[2],
                };
            }
            return null;
        }

        static string SurfaceType(Surface s)
        {
            if (s == null) return "other";
            if (s.IsPlane()) return "plane";
            if (s.IsCylinder()) return "cylinder";
            if (s.IsCone()) return "cone";
            if (s.IsSphere()) return "sphere";
            if (s.IsTorus()) return "torus";
            return "other";
        }

        static Dictionary<string, object> FaceEntry(ModelDoc2 doc, Face2 face)
        {
            Dictionary<string, object> f = new Dictionary<string, object>();
            f["ref"] = RefOf(doc, face);
            Surface s = face.GetSurface() as Surface;
            string type = SurfaceType(s);
            f["type"] = type;
            f["area"] = Finite(face.GetArea());
            if (type == "plane")
            {
                double[] frame = FaceFrame(face);
                if (frame != null)
                {
                    f["point"] = Vec(frame, 0);
                    f["sketch_x"] = Vec(frame, 3);
                    f["normal"] = Vec(frame, 6);
                }
            }
            else if (type == "cylinder")
            {
                double[] c = s.CylinderParams as double[];
                if (c != null && c.Length >= 7)
                {
                    f["point"] = Vec(c, 0);
                    f["axis"] = Vec(c, 3);
                    f["radius"] = Finite(c[6]);
                }
            }
            return f;
        }

        static Dictionary<string, object> EdgeEntry(ModelDoc2 doc, Edge edge)
        {
            Dictionary<string, object> e = new Dictionary<string, object>();
            e["ref"] = RefOf(doc, edge);
            Curve c = edge.GetCurve() as Curve;
            double[] p = edge.GetCurveParams2() as double[];
            bool closed = p != null && p.Length >= 6 && Math.Abs(p[0] - p[3]) < 1e-9 && Math.Abs(p[1] - p[4]) < 1e-9
                && Math.Abs(p[2] - p[5]) < 1e-9;
            string type = "other";
            if (c != null)
            {
                if (c.IsLine()) type = "line";
                else if (c.IsCircle()) type = closed ? "circle" : "arc";
                else if (c.IsEllipse()) type = "ellipse";
            }
            e["type"] = type;
            if (p != null && p.Length >= 8)
            {
                if (!closed)
                {
                    e["start"] = Vec(p, 0);
                    e["end"] = Vec(p, 3);
                }
                if (c != null) e["length"] = Finite(c.GetLength3(p[6], p[7]));
            }
            if (c != null && (type == "circle" || type == "arc"))
            {
                double[] cp = c.CircleParams as double[];
                if (cp != null && cp.Length >= 7)
                {
                    e["center"] = Vec(cp, 0);
                    e["radius"] = Finite(cp[6]);
                }
            }
            List<object> faces = new List<object>();
            object[] adjacent = edge.GetTwoAdjacentFaces2() as object[];
            if (adjacent != null)
            {
                foreach (object o in adjacent)
                {
                    string r = RefOf(doc, o);
                    if (r != null) faces.Add(r);
                }
            }
            e["faces"] = faces;
            return e;
        }

        static Dictionary<string, object> Properties(ModelDoc2 doc, string configuration)
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            CustomPropertyManager m = doc.Extension.get_CustomPropertyManager(configuration);
            string[] names = m == null ? null : m.GetNames() as string[];
            if (names == null) return d;
            foreach (string name in names)
            {
                string value, resolved;
                bool wasResolved, link;
                m.Get6(name, false, out value, out resolved, out wasResolved, out link);
                d[name] = value ?? "";
            }
            return d;
        }

        static object[] SolidBodies(ModelDoc2 doc)
        {
            PartDoc part = (PartDoc)doc;
            return part.GetBodies2((int)swBodyType_e.swSolidBody, false) as object[] ?? new object[0];
        }

        // Volume, area and centroid of the part's solid bodies, each body measured on its own
        // (IBody2.GetMassProperties), so the person's selection is neither used nor touched.
        // IMassProperty2.SelectedItems was the first way: setting it on a part faulted inside
        // SOLIDWORKS (RPC_E_SERVERFAULT, with the bodies as objects and as dispatch pointers alike;
        // measured with SOLIDWORKS 2024 SP1).
        static Dictionary<string, object> LiveMass(ModelDoc2 doc, object[] bodies)
        {
            Dictionary<string, object> m = new Dictionary<string, object>();
            double volume = 0, area = 0;
            double[] moment = new double[3];
            foreach (object o in bodies)
            {
                Body2 body = o as Body2;
                double[] p = body == null ? null : body.GetMassProperties(1.0) as double[];
                if (p == null || p.Length < 5) return m; // a body that cannot be measured: no figures
                volume += p[3];
                area += p[4];
                for (int i = 0; i < 3; i++) moment[i] += p[i] * p[3];
            }
            m["volume_m3"] = Finite(volume);
            m["surface_area_m2"] = Finite(area);
            if (volume > 0)
                m["center_of_mass_m"] = Vec(new double[] { moment[0] / volume, moment[1] / volume, moment[2] / volume }, 0);
            return m;
        }

        static double[] BodiesBox(object[] bodies)
        {
            List<BodyRef> refs = new List<BodyRef>();
            foreach (object o in bodies)
            {
                Body2 body = o as Body2;
                if (body == null) continue;
                BodyRef b = new BodyRef();
                b.Body = body;
                b.Visible = true;
                if (Extents(b)) refs.Add(b);
            }
            return Union(refs, delegate(BodyRef b) { return true; });
        }

        // What the snapshot was reading when SOLIDWORKS failed a call, for the error it reports.
        static string snapshotStage;

        static Dictionary<string, object> LiveSnapshot(Args args)
        {
            args.Allow("document", "limit");
            string key;
            ModelDoc2 doc = LivePart(args, out key);
            int limit = args.Int("limit", DefaultEntityLimit, 1, 1000000);
            snapshotStage = "the document";
            try
            {
                return Snapshot(doc, key, limit);
            }
            catch (COMException e)
            {
                Dictionary<string, object> details = new Dictionary<string, object>();
                details["stage"] = snapshotStage;
                details["hresult"] = e.ErrorCode;
                throw new BridgeException(Classify(e.ErrorCode), "reading the part failed at " + snapshotStage + ": " + e.Message, details);
            }
        }

        static Dictionary<string, object> Snapshot(ModelDoc2 doc, string key, int limit)
        {
            Stopwatch t = Stopwatch.StartNew();
            Dictionary<string, object> d = LiveDescribe(doc, key);
            d["path"] = doc.GetPathName() ?? "";
            d["length_unit"] = LengthUnit(doc);

            List<object> features = new List<object>(), dimensions = new List<object>();
            List<object> planes = new List<object>(), axes = new List<object>();
            Feature feature = doc.FirstFeature() as Feature;
            int walked = 0;
            while (feature != null && walked < 100000)
            {
                walked++;
                string type = feature.GetTypeName2();
                snapshotStage = "a " + type + " feature";
                string reference = FolderType(type) ? null : RefOf(doc, feature);
                if (reference != null)
                {
                    if (type == "RefPlane")
                    {
                        double[] frame = PlaneFrame(feature);
                        if (frame != null)
                        {
                            Dictionary<string, object> p = new Dictionary<string, object>();
                            p["ref"] = reference;
                            p["name"] = feature.Name;
                            p["origin"] = Vec(frame, 0);
                            p["sketch_x"] = Vec(frame, 3);
                            p["normal"] = Vec(frame, 6);
                            planes.Add(p);
                        }
                    }
                    else if (type == "RefAxis")
                    {
                        RefAxis axis = feature.GetSpecificFeature2() as RefAxis;
                        double[] ap = axis == null ? null : axis.GetRefAxisParams() as double[];
                        double[] dir = ap == null || ap.Length < 6 ? null : Unit(ap[3] - ap[0], ap[4] - ap[1], ap[5] - ap[2]);
                        if (dir != null)
                        {
                            Dictionary<string, object> a = new Dictionary<string, object>();
                            a["ref"] = reference;
                            a["name"] = feature.Name;
                            a["origin"] = Vec(ap, 0);
                            a["direction"] = Vec(dir, 0);
                            axes.Add(a);
                        }
                    }
                    else
                    {
                        Dictionary<string, object> f = new Dictionary<string, object>();
                        f["ref"] = reference;
                        f["name"] = feature.Name;
                        f["type"] = type;
                        f["suppressed"] = Suppressed(feature);
                        snapshotStage = "the parents of a " + type + " feature";
                        List<object> parents = new List<object>();
                        object[] up = feature.GetParents() as object[];
                        if (up != null)
                        {
                            foreach (object o in up)
                            {
                                string r = RefOf(doc, o);
                                if (r != null) parents.Add(r);
                            }
                        }
                        f["parents"] = parents;
                        features.Add(f);
                    }
                    snapshotStage = "the dimensions of a " + type + " feature";
                    foreach (KeyValuePair<Dimension, int> pair in FeatureDimensions(feature))
                    {
                        string kind = DimensionKind(pair.Value);
                        if (kind == null) continue;
                        Dictionary<string, object> dim = new Dictionary<string, object>();
                        dim["ref"] = "dim:" + reference + ":" + pair.Key.Name;
                        dim["name"] = pair.Key.Name + "@" + feature.Name;
                        dim["feature"] = reference;
                        dim["kind"] = kind;
                        dim["value"] = DimensionValue(pair.Key);
                        dimensions.Add(dim);
                    }
                }
                feature = feature.GetNextFeature() as Feature;
            }

            object[] bodies = SolidBodies(doc);
            List<object> faces = new List<object>(), edges = new List<object>();
            bool truncated = false;
            foreach (object o in bodies)
            {
                Body2 body = o as Body2;
                if (body == null) continue;
                object[] fs = body.GetFaces() as object[] ?? new object[0];
                object[] es = body.GetEdges() as object[] ?? new object[0];
                if (faces.Count + edges.Count + fs.Length + es.Length > limit)
                {
                    truncated = true;
                    break;
                }
                snapshotStage = "a face";
                foreach (object f in fs)
                {
                    Face2 face = f as Face2;
                    if (face != null) faces.Add(FaceEntry(doc, face));
                }
                snapshotStage = "an edge";
                foreach (object e in es)
                {
                    Edge edge = e as Edge;
                    if (edge != null) edges.Add(EdgeEntry(doc, edge));
                }
            }
            d["features"] = features;
            d["dimensions"] = dimensions;
            d["planes"] = planes;
            d["axes"] = axes;
            d["faces"] = faces;
            d["edges"] = edges;
            d["truncated"] = truncated;
            d["solid_bodies"] = bodies.Length;
            snapshotStage = "the mass properties";
            Dictionary<string, object> mass = LiveMass(doc, bodies);
            d["volume"] = mass.ContainsKey("volume_m3") ? mass["volume_m3"] : null;
            snapshotStage = "the extents";
            double[] box = BodiesBox(bodies);
            d["box_min"] = box == null ? null : Vec(box, 0);
            d["box_max"] = box == null ? null : Vec(box, 3);

            snapshotStage = "the custom properties";
            Configuration active = ActiveConfiguration(doc);
            d["custom_properties"] = Properties(doc, "");
            Dictionary<string, object> byConfiguration = new Dictionary<string, object>();
            if (active != null) byConfiguration[active.Name] = Properties(doc, active.Name);
            d["configuration_properties"] = byConfiguration;
            snapshotStage = "the material";
            string database;
            string material = ((PartDoc)doc).GetMaterialPropertyName2(active == null ? "" : active.Name, out database);
            d["material"] = string.IsNullOrEmpty(material) ? null : material;
            snapshotStage = "the equations";
            List<object> equations = new List<object>();
            EquationMgr eq = doc.GetEquationMgr() as EquationMgr;
            int count = eq == null ? 0 : eq.GetCount();
            for (int i = 0; i < count; i++) equations.Add(eq.get_Equation(i));
            d["equations"] = equations;
            snapshotStage = "the What's Wrong list";
            d["whats_wrong"] = WhatsWrong(doc);
            d["seconds"] = t.Elapsed.TotalSeconds;
            return d;
        }

        static Dictionary<string, object> LiveFeatures(Args args)
        {
            args.Allow("document", "limit");
            string key;
            ModelDoc2 doc = LiveDoc(args, out key);
            int limit = args.Int("limit", 10000, 1, 100000);
            List<object> features = new List<object>();
            Feature feature = doc.FirstFeature() as Feature;
            bool truncated = false;
            while (feature != null)
            {
                if (features.Count >= limit)
                {
                    truncated = true;
                    break;
                }
                Dictionary<string, object> f = new Dictionary<string, object>();
                f["name"] = feature.Name;
                f["type"] = feature.GetTypeName2();
                f["id"] = feature.GetID();
                f["suppressed"] = Suppressed(feature);
                features.Add(f);
                feature = feature.GetNextFeature() as Feature;
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["features"] = features;
            d["truncated"] = truncated;
            return d;
        }

        static Dictionary<string, object> LiveDimensions(Args args)
        {
            args.Allow("document", "limit");
            string key;
            ModelDoc2 doc = LiveDoc(args, out key);
            int limit = args.Int("limit", 10000, 1, 100000);
            List<object> dimensions = new List<object>();
            bool truncated = false;
            Feature feature = doc.FirstFeature() as Feature;
            while (feature != null && !truncated)
            {
                foreach (KeyValuePair<Dimension, int> pair in FeatureDimensions(feature))
                {
                    if (dimensions.Count >= limit)
                    {
                        truncated = true;
                        break;
                    }
                    Dictionary<string, object> dim = new Dictionary<string, object>();
                    dim["name"] = pair.Key.Name + "@" + feature.Name;
                    dim["feature"] = feature.Name;
                    dim["kind"] = DimensionKind(pair.Value) ?? "scalar";
                    dim["value"] = DimensionValue(pair.Key);
                    dimensions.Add(dim);
                }
                feature = feature.GetNextFeature() as Feature;
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["dimensions"] = dimensions;
            d["truncated"] = truncated;
            return d;
        }

        static Dictionary<string, object> LiveProperties(Args args)
        {
            args.Allow("document");
            string key;
            ModelDoc2 doc = LiveDoc(args, out key);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["properties"] = Properties(doc, "");
            Configuration active = ActiveConfiguration(doc);
            d["configuration"] = active == null ? null : active.Name;
            d["configuration_properties"] = active == null ? new Dictionary<string, object>() : Properties(doc, active.Name);
            return d;
        }

        static Dictionary<string, object> LiveMassProperties(Args args)
        {
            args.Allow("document", "configuration");
            string key;
            ModelDoc2 doc = LivePart(args, out key);
            Configuration active = ActiveConfiguration(doc);
            string wanted = args.String("configuration", null);
            if (wanted != null && (active == null || wanted != active.Name))
                throw new BridgeException("refused", "only the active configuration is measured in your SOLIDWORKS: showing another would change what you see");
            object[] bodies = SolidBodies(doc);
            Dictionary<string, object> d = LiveMass(doc, bodies);
            d["document"] = key;
            d["configuration"] = active == null ? null : active.Name;
            d["solid_bodies"] = bodies.Length;
            double[] box = BodiesBox(bodies);
            d["bbox_m"] = box == null ? null : new List<object> { Vec(box, 0), Vec(box, 3) };
            return d;
        }

        // ------------------------------------------------------------------ the safety copy and the undo entry
        // Where SolidSeas keeps its own files, as solidseas.ai.usage.data_dir says.
        static string StateFolder()
        {
            string cache = System.Environment.GetEnvironmentVariable("SOLIDSEAS_CACHE_DIR");
            if (!string.IsNullOrEmpty(cache)) return Path.GetFullPath(cache);
            string local = System.Environment.GetEnvironmentVariable("LOCALAPPDATA");
            if (string.IsNullOrEmpty(local)) local = System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData);
            return Path.Combine(local, "SolidSeas");
        }

        static string UndoStatePath(int pid)
        {
            return Path.Combine(StateFolder(), "live-undo-" + pid + ".txt");
        }

        static Dictionary<string, object> LiveCheckpoint(Args args)
        {
            args.Allow("document", "path");
            string key;
            ModelDoc2 doc = LivePart(args, out key);
            string target = args.FullPath("path");
            string runs = Path.GetFullPath(Path.Combine(StateFolder(), "runs"));
            string folder = Path.GetDirectoryName(target);
            if (folder == null || !string.Equals(Path.GetDirectoryName(folder), runs, StringComparison.OrdinalIgnoreCase))
                throw new BridgeException("refused", "a safety copy is written only into a run folder in " + runs);
            if (!CheckpointName.IsMatch(Path.GetFileName(target)))
                throw new BridgeException("invalid_argument", "a safety copy is named checkpoint-<run id>.sldprt");
            if (!Directory.Exists(folder)) throw new BridgeException("not_found", "no such folder: " + folder);
            if (File.Exists(target) || Directory.Exists(target))
                throw new BridgeException("refused", "the safety copy is there already, and is never replaced");
            string pathBefore = doc.GetPathName() ?? "";
            bool dirtyBefore = doc.GetSaveFlag();
            int errors = 0, warnings = 0;
            int options = (int)swSaveAsOptions_e.swSaveAsOptions_Silent | (int)swSaveAsOptions_e.swSaveAsOptions_Copy;
            bool ok = doc.Extension.SaveAs3(target, (int)swSaveAsVersion_e.swSaveAsCurrentVersion, options, null, null,
                                            ref errors, ref warnings);
            long bytes = File.Exists(target) ? new FileInfo(target).Length : 0;
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["errors"] = errors;
            d["warnings"] = warnings;
            if (errors != 0) d["error_names"] = FlagNames(typeof(swFileSaveError_e), errors);
            if (!ok || bytes == 0)
                throw new BridgeException("save_failed", ok ? "SaveAs3 reported success but wrote no copy" : "SaveAs3 failed", d);
            d["document"] = key;
            d["path"] = target;
            d["bytes"] = bytes;
            d["path_unchanged"] = string.Equals(doc.GetPathName() ?? "", pathBefore, StringComparison.OrdinalIgnoreCase);
            d["dirty_unchanged"] = doc.GetSaveFlag() == dirtyBefore;
            return d;
        }

        static string LockStatePath(int pid)
        {
            return Path.Combine(StateFolder(), "live-lock-" + pid + ".txt");
        }

        // Records, synced to disk, what the bridge is about to leave open in SOLIDWORKS, so that a
        // bridge started after this one was ended can undo it.
        static void WriteState(string path, string text)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            using (FileStream f = new FileStream(path, FileMode.CreateNew, FileAccess.Write))
            {
                byte[] bytes = System.Text.Encoding.UTF8.GetBytes(text);
                f.Write(bytes, 0, bytes.Length);
                f.Flush(true);
            }
        }

        static string ValidUndoName(string name)
        {
            if (name == null || !UndoName.IsMatch(name))
                throw new BridgeException("invalid_argument", "an undo entry is named SolidSeas script, SolidSeas step <n>: <operation> or SolidSeas revert of step <n>");
            return name;
        }

        // Opens one named undo entry on the part, recorded first in a state file.
        static void OpenUndoEntry(ModelDoc2 doc, string key, string name)
        {
            WriteState(UndoStatePath(livePid), key + "\n" + name);
            doc.Extension.StartRecordingUndoObject();
        }

        // Closes it, visible (Hidden false: answer 4), and forgets its record; whether it recorded anything.
        static bool CloseUndoEntry(ModelDoc2 doc, string name)
        {
            bool recorded = doc != null && doc.Extension.FinishRecordingUndoObject2(name, false);
            string state = UndoStatePath(livePid);
            if (File.Exists(state)) File.Delete(state);
            return recorded;
        }

        // Closes the undo entry a bridge recorded opening and never closed.
        static bool CloseLeftUndoEntry(int pid)
        {
            string state = UndoStatePath(pid);
            if (!File.Exists(state)) return false;
            string[] lines = File.ReadAllText(state).Split('\n');
            string name = lines.Length > 1 && UndoName.IsMatch(lines[1].Trim()) ? lines[1].Trim() : ScriptUndoName;
            ModelDoc2 doc = live == null ? null : FindLive(lines[0].Trim());
            bool closed = doc != null && doc.Extension.FinishRecordingUndoObject2(name, false);
            File.Delete(state);
            return closed;
        }

        // Unlocks the part a bridge recorded locking and never unlocked.
        static bool ReleaseLeftLock(int pid)
        {
            string state = LockStatePath(pid);
            if (!File.Exists(state)) return false;
            ModelDoc2 doc = live == null ? null : FindLive(File.ReadAllText(state).Trim());
            if (doc != null) doc.UnLock();
            File.Delete(state);
            return doc != null;
        }

        static Dictionary<string, object> LiveBeginUndo(Args args)
        {
            args.Allow("document", "name");
            string key;
            ModelDoc2 doc = LivePart(args, out key);
            string name = ValidUndoName(args.String("name", ScriptUndoName));
            // Only the app holding the writer changes the part, so an entry left open is an ended bridge's.
            bool closedLeft = CloseLeftUndoEntry(livePid);
            OpenUndoEntry(doc, key, name);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["name"] = name;
            d["left_entry_closed"] = closedLeft;
            return d;
        }

        static Dictionary<string, object> LiveEndUndo(Args args)
        {
            args.Allow("document", "name");
            RequireLive();
            string key = args.String("document", null);
            if (string.IsNullOrEmpty(key)) throw new BridgeException("invalid_argument", "document is required");
            string name = ValidUndoName(args.String("name", ScriptUndoName));
            ModelDoc2 doc = FindLive(key);
            bool recorded = CloseUndoEntry(doc, name);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["name"] = name;
            d["recorded"] = recorded;
            d["open"] = doc != null;
            return d;
        }

        // The What's Wrong list: each entry's feature, error code, and whether it is a warning.
        static List<object> WhatsWrong(ModelDoc2 doc)
        {
            List<object> list = new List<object>();
            object features, codes, warnings;
            if (!doc.Extension.GetWhatsWrong(out features, out codes, out warnings)) return list;
            object[] fs = features as object[];
            int[] cs = codes as int[];
            bool[] ws = warnings as bool[];
            if (fs == null || cs == null || ws == null) return list;
            for (int i = 0; i < fs.Length && i < cs.Length && i < ws.Length; i++)
            {
                Dictionary<string, object> e = new Dictionary<string, object>();
                e["feature"] = RefOf(doc, fs[i]);
                e["code"] = cs[i];
                e["warning"] = ws[i];
                list.Add(e);
            }
            return list;
        }

        // ------------------------------------------------------------------ operations
        static Dictionary<string, object> LiveOperation(Args args)
        {
            string key;
            ModelDoc2 doc = LivePart(args, out key);
            string op = args.String("op", null);
            string undoName = args.Has("undo_name") ? ValidUndoName(args.String("undo_name", null)) : null;
            bool lockPart = args.Bool("lock", false);
            Args opArgs = args.Without("undo_name", "lock");
            if (!IsActive(doc))
                throw new BridgeException("not_active", "bring the part to the front in SOLIDWORKS first: selection and sketching act on the active document");
            if (doc.SketchManager.ActiveSketch != null)
                throw new BridgeException("editing", "a sketch is open for editing in the part; close it first");
            // Only the app holding the writer changes the part, so what is left recorded is an ended bridge's.
            ReleaseLeftLock(livePid);
            if (undoName != null) CloseLeftUndoEntry(livePid);
            bool recorded = false;
            Dictionary<string, object> d;
            if (undoName != null) OpenUndoEntry(doc, key, undoName);
            try
            {
                if (lockPart)
                {
                    // Lock stops modifying commands from the user interface while the step runs (answer 3).
                    WriteState(LockStatePath(livePid), key);
                    doc.Lock();
                }
                try
                {
                    d = RunOperation(doc, opArgs, op);
                }
                finally
                {
                    if (lockPart)
                    {
                        try
                        {
                            doc.UnLock();
                            File.Delete(LockStatePath(livePid));
                        }
                        catch (Exception e) { Console.Error.WriteLine("unlocking the part: " + e.Message); }
                    }
                }
            }
            finally
            {
                if (undoName != null)
                {
                    try { recorded = CloseUndoEntry(doc, undoName); }
                    catch (Exception e) { Console.Error.WriteLine("closing the undo entry: " + e.Message); }
                }
            }
            d["document"] = key;
            d["op"] = op;
            d["dirty"] = doc.GetSaveFlag();
            d["undo_name"] = undoName;
            d["undo_recorded"] = recorded;
            return d;
        }

        static Dictionary<string, object> RunOperation(ModelDoc2 doc, Args args, string op)
        {
            Dictionary<string, object> d;
            switch (op)
            {
                case "set_dimension": d = SetDimension(doc, args); break;
                case "sketch_extrude_boss": d = SketchExtrude(doc, args, false); break;
                case "sketch_extrude_cut": d = SketchExtrude(doc, args, true); break;
                case "fillet": d = Fillet(doc, args); break;
                case "chamfer": d = Chamfer(doc, args); break;
                case "suppress": d = Suppression(doc, args, true); break;
                case "unsuppress": d = Suppression(doc, args, false); break;
                case "set_property": d = SetProperty(doc, args); break;
                case "shell":
                case "linear_pattern":
                case "circular_pattern":
                    throw new BridgeException("not_supported", op + " is in the vocabulary but not built in the bridge yet");
                default:
                    throw new BridgeException("unknown_op", "no live operation named " + (op ?? "(none)"));
            }
            return d;
        }

        static Dictionary<string, object> MadeFeature(ModelDoc2 doc, Feature feature)
        {
            string reference = RefOf(doc, feature);
            if (reference != null) madeHere.Add(reference);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["feature"] = reference;
            d["name"] = feature.Name;
            d["type"] = feature.GetTypeName2();
            bool warning;
            d["error"] = feature.GetErrorCode2(out warning);
            d["warning"] = warning;
            return d;
        }

        static void ExpectSelection(ModelDoc2 doc, int type, int count)
        {
            SelectionMgr selection = doc.SelectionManager as SelectionMgr;
            int n = selection == null ? 0 : selection.GetSelectedObjectCount2(-1);
            if (n != count)
                throw new BridgeException("selection_changed", count + " selected entities were expected and " + n + " were found: the selection changed before the feature was made");
            for (int i = 1; i <= n; i++)
            {
                int found = selection.GetSelectedObjectType3(i, -1);
                if (found != type)
                    throw new BridgeException("selection_changed", "selected entity " + i + " is of type " + found + ", not " + type + ": the selection changed before the feature was made");
            }
        }

        static void DeleteSelected(ModelDoc2 doc, Feature feature)
        {
            doc.ClearSelection2(true);
            if (feature.Select2(false, 0)) doc.Extension.DeleteSelection2((int)swDeleteSelectionOptions_e.swDelete_Absorbed);
            doc.ClearSelection2(true);
        }

        static Dimension FindDimension(ModelDoc2 doc, string reference)
        {
            // "dim:<the feature's persist reference>:<the dimension's own name>"
            int split = reference == null ? -1 : reference.LastIndexOf(':');
            if (reference == null || !reference.StartsWith("dim:", StringComparison.Ordinal) || split <= 4)
                throw new BridgeException("invalid_argument", "dimension is not a dimension reference");
            string name = reference.Substring(split + 1);
            if (name.Length == 0 || name.Length > 64 || name.IndexOfAny(new char[] { '@', '"', '\\', '/' }) >= 0)
                throw new BridgeException("invalid_argument", "dimension names no dimension");
            foreach (char c in name)
            {
                if (char.IsControl(c)) throw new BridgeException("invalid_argument", "dimension names no dimension");
            }
            Feature feature = Resolve(doc, reference.Substring(4, split - 4), "the dimension's feature", true) as Feature;
            if (feature == null) throw new BridgeException("not_found", "the dimension's feature is not a feature");
            Dimension dim = doc.Parameter(name + "@" + feature.Name) as Dimension;
            if (dim == null) throw new BridgeException("not_found", "the feature has no dimension of that name now");
            return dim;
        }

        static Dictionary<string, object> SetDimension(ModelDoc2 doc, Args args)
        {
            args.Allow("document", "op", "dimension", "value");
            Dimension dim = FindDimension(doc, args.String("dimension", null));
            double value = args.Number("value");
            object before = DimensionValue(dim);
            int status = dim.SetSystemValue3(value, (int)swSetValueInConfiguration_e.swSetValue_InThisConfiguration, null);
            if (status != (int)swSetValueReturnStatus_e.swSetValue_Successful)
                throw new BridgeException("failed", "SOLIDWORKS refused the value (SetSystemValue3 returned " + status + ")");
            bool rebuilt = doc.EditRebuild3();
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["before"] = before;
            d["after"] = DimensionValue(dim);
            d["rebuilt"] = rebuilt;
            return d;
        }

        sealed class ProfileSegment
        {
            public string Kind;
            public double[] Start, End, Center;
            public double Radius;
            public bool Clockwise;
        }

        static double[] Point2(object raw, string what)
        {
            object[] xy = raw as object[];
            if (xy == null || xy.Length != 2) throw new BridgeException("invalid_argument", what + " must be [x, y]");
            return new double[] { Args.NumberOf(xy[0], what), Args.NumberOf(xy[1], what) };
        }

        static List<ProfileSegment> Segments(object[] raw)
        {
            if (raw.Length < 1 || raw.Length > 64) throw new BridgeException("invalid_argument", "a profile has 1 to 64 segments");
            List<ProfileSegment> list = new List<ProfileSegment>();
            for (int i = 0; i < raw.Length; i++)
            {
                string what = "segment " + (i + 1);
                Args s = Args.Item(raw[i], "segments");
                ProfileSegment seg = new ProfileSegment();
                seg.Kind = s.String("type", null);
                if (seg.Kind == "line")
                {
                    s.Allow("type", "start", "end");
                    seg.Start = Point2(s.Raw("start"), what + " start");
                    seg.End = Point2(s.Raw("end"), what + " end");
                }
                else if (seg.Kind == "arc")
                {
                    s.Allow("type", "center", "start", "end", "clockwise");
                    seg.Center = Point2(s.Raw("center"), what + " center");
                    seg.Start = Point2(s.Raw("start"), what + " start");
                    seg.End = Point2(s.Raw("end"), what + " end");
                    seg.Clockwise = s.Bool("clockwise", false);
                }
                else if (seg.Kind == "circle")
                {
                    s.Allow("type", "center", "radius");
                    seg.Center = Point2(s.Raw("center"), what + " center");
                    seg.Radius = s.Number("radius");
                    if (!(seg.Radius > 0)) throw new BridgeException("invalid_argument", what + " radius must be more than 0");
                }
                else throw new BridgeException("invalid_argument", what + " type must be line, arc or circle");
                list.Add(seg);
            }
            return list;
        }

        // A point of the frame's plane (u along x, v along normal x x) in the sketch's own coordinates.
        static double[] ToSketch(MathUtility math, MathTransform toSketch, double[] frame, double u, double v)
        {
            double[] x = { frame[3], frame[4], frame[5] };
            double[] n = { frame[6], frame[7], frame[8] };
            double[] y = { n[1] * x[2] - n[2] * x[1], n[2] * x[0] - n[0] * x[2], n[0] * x[1] - n[1] * x[0] };
            double[] model = {
                frame[0] + u * x[0] + v * y[0],
                frame[1] + u * x[1] + v * y[1],
                frame[2] + u * x[2] + v * y[2],
            };
            MathPoint p = math.CreatePoint(model) as MathPoint;
            MathPoint q = p == null ? null : p.MultiplyTransform(toSketch) as MathPoint;
            double[] s = q == null ? null : q.ArrayData as double[];
            if (s == null || s.Length < 3) throw new BridgeException("failed", "a profile point could not be put into the sketch");
            if (Math.Abs(s[2]) > OnPlane)
                throw new BridgeException("failed", "the profile is not in the sketch's plane (" + s[2] + " m off it)");
            return s;
        }

        static Dictionary<string, object> SketchExtrude(ModelDoc2 doc, Args args, bool cut)
        {
            args.Allow("document", "op", "plane", "segments", "depth", "direction", "end");
            List<ProfileSegment> segments = Segments(args.List("segments"));
            string direction = args.String("direction", "normal");
            if (direction != "normal" && direction != "reversed")
                throw new BridgeException("invalid_argument", "direction must be normal or reversed");
            string end = args.String("end", "blind");
            if (end != "blind" && !(cut && end == "through_all"))
                throw new BridgeException("invalid_argument", cut ? "end must be blind or through_all" : "end must be blind");
            double depth = 0;
            if (end == "blind")
            {
                depth = args.Number("depth");
                if (!(depth > 0)) throw new BridgeException("invalid_argument", "depth must be more than 0");
            }
            else if (args.Has("depth")) throw new BridgeException("invalid_argument", "a through-all cut takes no depth");

            object entity = Resolve(doc, args.String("plane", null), "plane", false);
            Feature planeFeature = entity as Feature;
            Face2 face = planeFeature == null ? entity as Face2 : null;
            double[] frame;
            int selectType;
            if (planeFeature != null && planeFeature.GetTypeName2() == "RefPlane")
            {
                frame = PlaneFrame(planeFeature);
                selectType = (int)swSelectType_e.swSelDATUMPLANES;
            }
            else if (face != null)
            {
                frame = FaceFrame(face);
                selectType = (int)swSelectType_e.swSelFACES;
                if (frame == null) throw new BridgeException("invalid_argument", "plane names a face that is not planar");
            }
            else throw new BridgeException("invalid_argument", "plane names neither a reference plane nor a planar face");
            if (frame == null) throw new BridgeException("failed", "the plane's frame could not be read");

            doc.ClearSelection2(true);
            bool selected = planeFeature != null ? planeFeature.Select2(false, 0) : ((Entity)face).Select4(false, null);
            if (!selected) throw new BridgeException("failed", "the plane could not be selected");
            ExpectSelection(doc, selectType, 1);
            SketchManager sm = doc.SketchManager;
            sm.InsertSketch(true);
            Sketch sketch = sm.ActiveSketch;
            if (sketch == null) throw new BridgeException("failed", "SOLIDWORKS opened no sketch on the plane");
            Feature sketchFeature = (Feature)sketch;
            Feature made = null;
            try
            {
                MathTransform toSketch = sketch.ModelToSketchTransform;
                MathUtility math = live.GetMathUtility() as MathUtility;
                if (toSketch == null || math == null) throw new BridgeException("failed", "the sketch's transform could not be read");
                // Arcs turn the frame's way; a sketch whose axes run the other way about the normal turns them back.
                double[] o = ToSketch(math, toSketch, frame, 0, 0), ux = ToSketch(math, toSketch, frame, 1, 0), vy = ToSketch(math, toSketch, frame, 0, 1);
                bool mirrored = (ux[0] - o[0]) * (vy[1] - o[1]) - (ux[1] - o[1]) * (vy[0] - o[0]) < 0;
                bool addToDb = sm.AddToDB, display = sm.DisplayWhenAdded;
                sm.AddToDB = true;
                sm.DisplayWhenAdded = false;
                try
                {
                    int n = 0;
                    foreach (ProfileSegment s in segments)
                    {
                        n++;
                        SketchSegment drawn;
                        if (s.Kind == "line")
                        {
                            double[] a = ToSketch(math, toSketch, frame, s.Start[0], s.Start[1]);
                            double[] b = ToSketch(math, toSketch, frame, s.End[0], s.End[1]);
                            drawn = sm.CreateLine(a[0], a[1], 0, b[0], b[1], 0);
                        }
                        else if (s.Kind == "arc")
                        {
                            double[] c = ToSketch(math, toSketch, frame, s.Center[0], s.Center[1]);
                            double[] a = ToSketch(math, toSketch, frame, s.Start[0], s.Start[1]);
                            double[] b = ToSketch(math, toSketch, frame, s.End[0], s.End[1]);
                            short turn = (short)((s.Clockwise != mirrored) ? -1 : 1);
                            drawn = sm.CreateArc(c[0], c[1], 0, a[0], a[1], 0, b[0], b[1], 0, turn);
                        }
                        else
                        {
                            double[] c = ToSketch(math, toSketch, frame, s.Center[0], s.Center[1]);
                            drawn = sm.CreateCircleByRadius(c[0], c[1], 0, s.Radius);
                        }
                        if (drawn == null) throw new BridgeException("failed", "SOLIDWORKS did not draw segment " + n + " of the profile");
                    }
                }
                finally
                {
                    sm.AddToDB = addToDb;
                    sm.DisplayWhenAdded = display;
                }
                sm.InsertSketch(true);
                doc.ClearSelection2(true);
                if (!sketchFeature.Select2(false, 0)) throw new BridgeException("failed", "the new sketch could not be selected");
                ExpectSelection(doc, (int)swSelectType_e.swSelSKETCHES, 1);
                FeatureManager fm = doc.FeatureManager;
                bool reversed = direction == "reversed";
                if (cut)
                {
                    int t1 = end == "blind" ? (int)swEndConditions_e.swEndCondBlind : (int)swEndConditions_e.swEndCondThroughAll;
                    made = fm.FeatureCut4(true, false, reversed, t1, 0, depth, 0, false, false, false, false, 0, 0,
                                          false, false, false, false, false, true, true, false, false, false,
                                          (int)swStartConditions_e.swStartSketchPlane, 0, false, false);
                }
                else
                {
                    made = fm.FeatureExtrusion3(true, false, reversed, (int)swEndConditions_e.swEndCondBlind, 0, depth, 0,
                                                false, false, false, false, 0, 0, false, false, false, false, true, true, true,
                                                (int)swStartConditions_e.swStartSketchPlane, 0, false);
                }
                doc.ClearSelection2(true);
                if (made == null) throw new BridgeException("failed", "SOLIDWORKS made no " + (cut ? "cut" : "boss") + " from the profile");
            }
            catch
            {
                // The sketch this call made goes again, and nothing else.
                try
                {
                    if (sm.ActiveSketch != null) sm.InsertSketch(true);
                    if (made == null) DeleteSelected(doc, sketchFeature);
                }
                catch (Exception e)
                {
                    Console.Error.WriteLine("removing the sketch after a failed extrude: " + e.Message);
                }
                throw;
            }
            Dictionary<string, object> d = MadeFeature(doc, made);
            d["sketch"] = RefOf(doc, sketchFeature);
            return d;
        }

        static object[] Edges(ModelDoc2 doc, object[] refs)
        {
            if (refs.Length < 1 || refs.Length > 64) throw new BridgeException("invalid_argument", "edges must name 1 to 64 edges");
            HashSet<string> seen = new HashSet<string>();
            object[] edges = new object[refs.Length];
            for (int i = 0; i < refs.Length; i++)
            {
                string r = refs[i] as string;
                if (r == null || !seen.Add(r)) throw new BridgeException("invalid_argument", "edges must name each edge once, by its reference");
                Edge edge = Resolve(doc, r, "edge " + (i + 1), false) as Edge;
                if (edge == null) throw new BridgeException("invalid_argument", "edge " + (i + 1) + " is not an edge");
                edges[i] = edge;
            }
            return edges;
        }

        static Dictionary<string, object> Fillet(ModelDoc2 doc, Args args)
        {
            args.Allow("document", "op", "edges", "radius");
            double radius = args.Number("radius");
            if (!(radius > 0)) throw new BridgeException("invalid_argument", "radius must be more than 0");
            object[] edges = Edges(doc, args.List("edges"));
            // A fillet definition naming its edges (CreateDefinition, CreateFeature) made no fillet,
            // with the edges as objects or as dispatch pointers (measured with SOLIDWORKS 2024 SP1),
            // so the edges are selected, with mark 1 as FeatureFillet3 reads them, and the selection
            // is checked just before the call, as for a chamfer.
            SelectionMgr selection = doc.SelectionManager as SelectionMgr;
            SelectData marked = selection == null ? null : selection.CreateSelectData();
            if (marked == null) throw new BridgeException("failed", "the edges could not be selected");
            marked.Mark = 1;
            doc.ClearSelection2(true);
            foreach (object e in edges)
            {
                if (!((Entity)e).Select4(true, marked)) throw new BridgeException("failed", "an edge could not be selected");
            }
            ExpectSelection(doc, (int)swSelectType_e.swSelEDGES, edges.Length);
            // A constant radius on these edges only: uniform radius, no propagation along tangent edges.
            int options = (int)swFeatureFilletOptions_e.swFeatureFilletUniformRadius
                | (int)swFeatureFilletOptions_e.swFeatureFilletAttachEdges
                | (int)swFeatureFilletOptions_e.swFeatureFilletKeepFeatures;
            Feature made = doc.FeatureManager.FeatureFillet3(options, radius, 0, 0,
                (int)swFeatureFilletType_e.swFeatureFilletType_Simple, (int)swFilletOverFlowType_e.swFilletOverFlowType_Default,
                0, null, null, null, null, null, null, null) as Feature;
            doc.ClearSelection2(true);
            if (made == null) throw new BridgeException("failed", "SOLIDWORKS made no fillet: the radius may not fit the edges");
            return MadeFeature(doc, made);
        }

        static Dictionary<string, object> Chamfer(ModelDoc2 doc, Args args)
        {
            args.Allow("document", "op", "edges", "distance");
            double distance = args.Number("distance");
            if (!(distance > 0)) throw new BridgeException("invalid_argument", "distance must be more than 0");
            object[] edges = Edges(doc, args.List("edges"));
            doc.ClearSelection2(true);
            foreach (object e in edges)
            {
                if (!((Entity)e).Select4(true, null)) throw new BridgeException("failed", "an edge could not be selected");
            }
            ExpectSelection(doc, (int)swSelectType_e.swSelEDGES, edges.Length);
            // Equal distances: a distance and 45 degrees, no tangent propagation.
            Feature made = doc.FeatureManager.InsertFeatureChamfer(0, (int)swChamferType_e.swChamferAngleDistance, distance,
                                                                   Math.PI / 4, 0, 0, 0, 0);
            doc.ClearSelection2(true);
            if (made == null) throw new BridgeException("failed", "SOLIDWORKS made no chamfer: the distance may not fit the edges");
            return MadeFeature(doc, made);
        }

        static Dictionary<string, object> Suppression(ModelDoc2 doc, Args args, bool suppress)
        {
            args.Allow("document", "op", "features");
            object[] refs = args.List("features");
            if (refs.Length < 1 || refs.Length > 16) throw new BridgeException("invalid_argument", "features must name 1 to 16 features");
            List<object> changed = new List<object>();
            foreach (object r in refs)
            {
                Feature f = Resolve(doc, r as string, "a feature", true) as Feature;
                if (f == null) throw new BridgeException("invalid_argument", "features names something that is not a feature");
                Dictionary<string, object> one = new Dictionary<string, object>();
                one["feature"] = r;
                one["name"] = f.Name;
                one["was_suppressed"] = Suppressed(f);
                int action = suppress ? (int)swFeatureSuppressionAction_e.swSuppressFeature : (int)swFeatureSuppressionAction_e.swUnSuppressFeature;
                if (!f.SetSuppression2(action, (int)swInConfigurationOpts_e.swThisConfiguration, null))
                    throw new BridgeException("failed", "SOLIDWORKS did not " + (suppress ? "suppress " : "unsuppress ") + f.Name);
                one["suppressed"] = Suppressed(f);
                changed.Add(one);
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["features"] = changed;
            d["rebuilt"] = doc.EditRebuild3();
            return d;
        }

        static string Folded(string name)
        {
            return name.Replace(" ", "").ToLowerInvariant();
        }

        static Dictionary<string, object> SetProperty(ModelDoc2 doc, Args args)
        {
            args.Allow("document", "op", "name", "value", "scope");
            string name = args.String("name", null), value = args.String("value", null), scope = args.String("scope", "file");
            if (string.IsNullOrEmpty(name) || name.Length > 64 || value == null || value.Length > 64)
                throw new BridgeException("invalid_argument", "a property's name is 1 to 64 characters and its value at most 64");
            foreach (char c in name + value)
            {
                if (char.IsControl(c) || c == '@' || c == '"' || c == '\\' || c == '/')
                    throw new BridgeException("invalid_argument", "a property's name and value hold printable characters other than @ \" \\ /");
            }
            if (Array.IndexOf(ProtectedProperties, Folded(name)) >= 0)
                throw new BridgeException("refused", "the property " + name + " is one downstream systems key on, and is never written");
            if (value.Length > 0 && "=+-@".IndexOf(value[0]) >= 0)
                throw new BridgeException("refused", "a property value must not start with =, +, - or @");
            if (scope != "file" && scope != "configuration") throw new BridgeException("invalid_argument", "scope must be file or configuration");
            Configuration active = ActiveConfiguration(doc);
            if (scope == "configuration" && active == null) throw new BridgeException("failed", "the part has no active configuration");
            string configuration = scope == "file" ? "" : active.Name;
            CustomPropertyManager m = doc.Extension.get_CustomPropertyManager(configuration);
            if (m == null) throw new BridgeException("failed", "the part's custom properties could not be read");
            Dictionary<string, object> before = Properties(doc, configuration);
            int result = m.Add3(name, (int)swCustomInfoType_e.swCustomInfoText, value,
                                (int)swCustomPropertyAddOption_e.swCustomPropertyReplaceValue);
            if (result != (int)swCustomInfoAddResult_e.swCustomInfoAddResult_AddedOrChanged)
                throw new BridgeException("failed", "SOLIDWORKS did not set the property (Add3 returned " + result + ")");
            propertiesSetHere.Add(PropertyKey(doc, configuration, name));
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["name"] = name;
            d["scope"] = scope;
            d["configuration"] = scope == "file" ? null : configuration;
            d["before"] = before.ContainsKey(name) ? before[name] : null;
            d["after"] = value;
            return d;
        }

        static string PropertyKey(ModelDoc2 doc, string configuration, string name)
        {
            string path = doc.GetPathName() ?? "";
            return (path.Length == 0 ? doc.GetTitle() : path.ToLowerInvariant()) + "\n" + configuration + "\n" + name;
        }

        // The inverse of set_property: the value it had, or no property when it had none. Only for a
        // property this bridge set.
        static Dictionary<string, object> LiveRestoreProperty(Args args)
        {
            args.Allow("document", "name", "scope", "value");
            string key;
            ModelDoc2 doc = LivePart(args, out key);
            string name = args.String("name", null), scope = args.String("scope", "file"), value = args.String("value", null);
            if (scope != "file" && scope != "configuration") throw new BridgeException("invalid_argument", "scope must be file or configuration");
            Configuration active = ActiveConfiguration(doc);
            if (scope == "configuration" && active == null) throw new BridgeException("failed", "the part has no active configuration");
            string configuration = scope == "file" ? "" : active.Name;
            if (name == null || !propertiesSetHere.Contains(PropertyKey(doc, configuration, name)))
                throw new BridgeException("refused", "only a property this bridge set is put back");
            CustomPropertyManager m = doc.Extension.get_CustomPropertyManager(configuration);
            if (m == null) throw new BridgeException("failed", "the part's custom properties could not be read");
            int result = value == null
                ? m.Delete2(name)
                : m.Add3(name, (int)swCustomInfoType_e.swCustomInfoText, value, (int)swCustomPropertyAddOption_e.swCustomPropertyReplaceValue);
            bool ok = value == null
                ? result == (int)swCustomInfoDeleteResult_e.swCustomInfoDeleteResult_OK || result == (int)swCustomInfoDeleteResult_e.swCustomInfoDeleteResult_NotPresent
                : result == (int)swCustomInfoAddResult_e.swCustomInfoAddResult_AddedOrChanged;
            if (!ok) throw new BridgeException("failed", "SOLIDWORKS did not put the property back (it returned " + result + ")");
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["name"] = name;
            d["scope"] = scope;
            d["value"] = value;
            return d;
        }

        // The persist reference each given one has now. A step can give an entity a new
        // reference while the old one still resolves to it (measured with SOLIDWORKS 2024 SP1:
        // the top face of a block after a fillet on its edges), so a run maps a plan's references
        // before each step; null for one that names nothing now.
        static Dictionary<string, object> LiveCurrentRefs(Args args)
        {
            args.Allow("document", "refs");
            string key;
            ModelDoc2 doc = LivePart(args, out key);
            object[] refs = args.List("refs");
            if (refs.Length > 1000) throw new BridgeException("invalid_argument", "at most 1,000 references at once");
            Dictionary<string, object> map = new Dictionary<string, object>();
            foreach (object o in refs)
            {
                string reference = o as string;
                if (reference == null) throw new BridgeException("invalid_argument", "refs must be persist references");
                map[reference] = CurrentRef(doc, reference);
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["refs"] = map;
            return d;
        }

        static string CurrentRef(ModelDoc2 doc, string reference)
        {
            try
            {
                if (reference.StartsWith("dim:", StringComparison.Ordinal))
                {
                    int split = reference.LastIndexOf(':');
                    if (split <= 4) return null;
                    FindDimension(doc, reference); // the dimension is there now
                    Feature feature = Resolve(doc, reference.Substring(4, split - 4), "the dimension's feature", true) as Feature;
                    string now = RefOf(doc, feature);
                    return now == null ? null : "dim:" + now + reference.Substring(split);
                }
                return RefOf(doc, Resolve(doc, reference, "the reference", true));
            }
            catch (BridgeException)
            {
                return null;
            }
        }

        static Dictionary<string, object> LiveDeleteFeature(Args args)
        {
            args.Allow("document", "feature");
            string key;
            ModelDoc2 doc = LivePart(args, out key);
            string reference = args.String("feature", null);
            if (reference == null || !madeHere.Contains(reference))
                throw new BridgeException("refused", "only a feature this bridge made is deleted");
            Feature feature = Resolve(doc, reference, "the feature", true) as Feature;
            if (feature == null) throw new BridgeException("not_found", "the reference names no feature");
            doc.ClearSelection2(true);
            if (!feature.Select2(false, 0)) throw new BridgeException("failed", "the feature could not be selected");
            SelectionMgr selection = doc.SelectionManager as SelectionMgr;
            if (selection == null || selection.GetSelectedObjectCount2(-1) != 1)
                throw new BridgeException("selection_changed", "the selection changed before the feature was deleted");
            bool deleted = doc.Extension.DeleteSelection2((int)swDeleteSelectionOptions_e.swDelete_Absorbed);
            doc.ClearSelection2(true);
            if (!deleted) throw new BridgeException("failed", "SOLIDWORKS did not delete the feature");
            madeHere.Remove(reference);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["feature"] = reference;
            d["deleted"] = true;
            return d;
        }
    }
}
