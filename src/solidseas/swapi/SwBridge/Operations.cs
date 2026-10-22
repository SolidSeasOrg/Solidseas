// The bridge's named operations: everything it does in SOLIDWORKS.
//
// Batch mode, here: the bridge starts its own SLDWORKS.exe, finds it in the Running
// Object Table under the moniker "SolidWorks_PID_<pid>" of that process alone (never
// GetActiveObject, never another SOLIDWORKS), hides it and its journal file message box,
// and ends it, through the Job Object that holds it, when asked, when standard input
// closes, or when the bridge itself is ended. Live mode (Live.cs) attaches to a
// SOLIDWORKS the person started, by the same moniker, and never ends it.
//
// It sets no SOLIDWORKS option or user preference (they are shared, through the
// registry, with every session of the Windows account), and never runs SOLIDWORKS' own
// shutdown, ExitApp, which writes the instance's toolbar and CommandManager layout there.
// It creates documents only from a template path given explicitly (import_file too, unless
// asked to load a file the way SOLIDWORKS' File Open does, Import.cs), opens documents
// read-only only, writes copies with IModelDocExtension.SaveAs3 and swSaveAsOptions_Copy
// to export formats only, never over the file of a document open in the instance under
// any name, and closes only the documents it opened or created. Measure.cs measures them.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Threading;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace SolidSeas.SwBridge
{
    static class Rot
    {
        [DllImport("ole32.dll")]
        static extern int GetRunningObjectTable(int reserved, out IRunningObjectTable rot);
        [DllImport("ole32.dll")]
        static extern int CreateBindCtx(int reserved, out IBindCtx ctx);

        // The object registered under exactly "SolidWorks_PID_<pid>", or null.
        public static object Find(int pid)
        {
            IRunningObjectTable rot;
            if (GetRunningObjectTable(0, out rot) != 0 || rot == null) return null;
            IEnumMoniker monikers = null;
            IBindCtx ctx = null;
            string want = "SolidWorks_PID_" + pid;
            try
            {
                rot.EnumRunning(out monikers);
                if (monikers == null || CreateBindCtx(0, out ctx) != 0) return null;
                IMoniker[] one = new IMoniker[1];
                while (monikers.Next(1, one, IntPtr.Zero) == 0)
                {
                    try
                    {
                        string name = null;
                        try { one[0].GetDisplayName(ctx, null, out name); }
                        catch (COMException) { }
                        if (name != null && string.Equals(name.TrimStart('!'), want, StringComparison.OrdinalIgnoreCase))
                        {
                            object instance;
                            if (rot.GetObject(one[0], out instance) == 0) return instance;
                        }
                    }
                    finally
                    {
                        Marshal.ReleaseComObject(one[0]);
                    }
                }
                return null;
            }
            finally
            {
                if (ctx != null) Marshal.ReleaseComObject(ctx);
                if (monikers != null) Marshal.ReleaseComObject(monikers);
                Marshal.ReleaseComObject(rot);
            }
        }
    }

    // Change, save, undo and close notifications of one part, sent as event lines.
    sealed class PartWatch
    {
        readonly int handle;
        readonly PartDoc part;

        public PartWatch(int handle, PartDoc part)
        {
            this.handle = handle;
            this.part = part;
            part.ModifyNotify += OnModify;
            part.FileSaveNotify += OnFileSave;
            part.FileSavePostNotify += OnFileSavePost;
            part.UndoPostNotify += OnUndoPost;
            part.RedoPostNotify += OnRedoPost;
            part.DestroyNotify2 += OnDestroy;
            part.AddItemNotify += OnAddItem;
            part.DeleteItemNotify += OnDeleteItem;
            part.RegenPostNotify2 += OnRegenPost;
            part.ChangeCustomPropertyNotify += OnChangeCustomProperty;
            part.ActiveConfigChangePostNotify += OnActiveConfigChangePost;
        }

        public static readonly string[] Names = {
            "ModifyNotify", "FileSaveNotify", "FileSavePostNotify", "UndoPostNotify", "RedoPostNotify",
            "DestroyNotify2", "AddItemNotify", "DeleteItemNotify", "RegenPostNotify2",
            "ChangeCustomPropertyNotify", "ActiveConfigChangePostNotify",
        };

        public void Stop()
        {
            part.ModifyNotify -= OnModify;
            part.FileSaveNotify -= OnFileSave;
            part.FileSavePostNotify -= OnFileSavePost;
            part.UndoPostNotify -= OnUndoPost;
            part.RedoPostNotify -= OnRedoPost;
            part.DestroyNotify2 -= OnDestroy;
            part.AddItemNotify -= OnAddItem;
            part.DeleteItemNotify -= OnDeleteItem;
            part.RegenPostNotify2 -= OnRegenPost;
            part.ChangeCustomPropertyNotify -= OnChangeCustomProperty;
            part.ActiveConfigChangePostNotify -= OnActiveConfigChangePost;
        }

        void Emit(string name, Dictionary<string, object> data)
        {
            Dictionary<string, object> e = new Dictionary<string, object>();
            e["event"] = "document";
            e["doc"] = handle;
            e["name"] = name;
            if (data != null) e["data"] = data;
            // SOLIDWORKS waits for this handler: queue the line and return, never wait for the pipe.
            Output.Event(e);
        }

        static Dictionary<string, object> Data(params object[] pairs)
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            for (int i = 0; i + 1 < pairs.Length; i += 2) d[(string)pairs[i]] = pairs[i + 1];
            return d;
        }

        int OnModify() { Emit("ModifyNotify", null); return 0; }
        int OnFileSave(string fileName) { Emit("FileSaveNotify", Data("file", fileName)); return 0; }
        int OnFileSavePost(int saveType, string fileName) { Emit("FileSavePostNotify", Data("save_type", saveType, "file", fileName)); return 0; }
        int OnUndoPost() { Emit("UndoPostNotify", null); return 0; }
        int OnRedoPost() { Emit("RedoPostNotify", null); return 0; }
        int OnDestroy(int destroyType) { Emit("DestroyNotify2", Data("destroy_type", destroyType)); return 0; }
        int OnAddItem(int entityType, string itemName) { Emit("AddItemNotify", Data("entity_type", entityType, "item", itemName)); return 0; }
        int OnDeleteItem(int entityType, string itemName) { Emit("DeleteItemNotify", Data("entity_type", entityType, "item", itemName)); return 0; }
        int OnRegenPost(object stopFeature) { Emit("RegenPostNotify2", null); return 0; }
        int OnChangeCustomProperty(string propName, string configuration, string oldValue, string newValue, int valueType)
        {
            Emit("ChangeCustomPropertyNotify", Data("property", propName, "configuration", configuration));
            return 0;
        }
        int OnActiveConfigChangePost() { Emit("ActiveConfigChangePostNotify", null); return 0; }
    }

    static partial class Operations
    {
        // Export formats only. A native SOLIDWORKS file (.sldprt, .sldasm, .slddrw) is never
        // written by save_copy; an operation that needs one will check its own target.
        static readonly string[] SaveExtensions = {
            ".step", ".stp", ".x_t", ".x_b", ".stl", ".3mf", ".gltf", ".glb",
        };

        // The exit code of every process in the job when the bridge ends its instance ("SS").
        public const uint EndedExitCode = 0x5353;

        static OwnedProcess process;
        static WindowWatch watch;
        static ISldWorks sw;
        static readonly Dictionary<int, ModelDoc2> documents = new Dictionary<int, ModelDoc2>();
        static readonly Dictionary<int, PartWatch> watches = new Dictionary<int, PartWatch>();
        static int nextHandle = 1;
        // One SolidSeas-started SOLIDWORKS at a time in this Windows session, across bridges.
        const string InstanceMutexName = @"Local\SolidSeas-SwBridge-SolidWorks";
        static Mutex instanceMutex;

        public static void Register(Dictionary<string, Handler> handlers)
        {
            handlers["start_solidworks"] = StartSolidWorks;
            handlers["solidworks_info"] = SolidWorksInfo;
            handlers["exit_solidworks"] = ExitSolidWorks;
            handlers["new_document"] = NewDocument;
            handlers["open_document"] = OpenDocument;
            handlers["document_info"] = DocumentInfo;
            handlers["list_features"] = ListFeatures;
            handlers["save_copy"] = SaveCopy;
            handlers["close_document"] = CloseDocument;
            handlers["watch_document"] = WatchDocument;
            handlers["unwatch_document"] = UnwatchDocument;
            handlers["mass_properties"] = MassProperties;
            handlers["import_file"] = ImportFile;
            RegisterNativeCheck(handlers);
            RegisterLive(handlers);
        }

        public static object StartedPid()
        {
            return process != null && !process.HasExited ? (object)process.Id : null;
        }

        public static string Classify(int hresult)
        {
            switch (unchecked((uint)hresult))
            {
                case 0x80010001u: return "busy";          // RPC_E_CALL_REJECTED: still busy at the deadline
                case 0x80010002u: return "cancelled";     // RPC_E_CALL_CANCELED
                case 0x80010108u:                         // RPC_E_DISCONNECTED
                case 0x800706BAu:                         // RPC_S_SERVER_UNAVAILABLE
                case 0x800706BEu:                         // RPC_S_CALL_FAILED
                    return "disconnected";
                default: return "com_error";
            }
        }

        static ISldWorks Require()
        {
            if (sw == null || process == null) throw new BridgeException("not_started", "start_solidworks first");
            if (process.HasExited) throw new BridgeException("disconnected", "SLDWORKS.exe (PID " + process.Id + ") has exited");
            return sw;
        }

        static Dictionary<string, object> StartSolidWorks(Args args)
        {
            args.Allow("exe");
            if (process != null)
            {
                if (!process.HasExited) throw new BridgeException("refused", "this bridge already runs SOLIDWORKS (PID " + process.Id + ")");
                EndSolidWorks(1000);
            }
            string exe = args.String("exe", null) == null
                ? Path.Combine(Program.DefaultSolidWorksFolder, "SLDWORKS.exe")
                : args.FullPath("exe");
            if (!string.Equals(Path.GetFileName(exe), "SLDWORKS.exe", StringComparison.OrdinalIgnoreCase))
                throw new BridgeException("invalid_argument", "exe must be a path to SLDWORKS.exe");
            if (!File.Exists(exe)) throw new BridgeException("not_found", "SOLIDWORKS not found: " + exe);

            TakeInstanceMutex();
            try
            {
                process = OwnedProcess.Start(exe);
            }
            catch
            {
                ReleaseInstanceMutex();
                throw;
            }
            // Live mode's session list tells this instance from the person's own by this mark.
            MarkBatch(process.Id);
            try
            {
                // From the first moment: the journal file message box, and SOLIDWORKS Product
                // Activation, come while it starts.
                watch = WindowWatch.Start(process);
                object found;
                while ((found = Rot.Find(process.Id)) == null)
                {
                    if (process.HasExited)
                        throw new BridgeException("start_failed", "SLDWORKS.exe (PID " + process.Id + ") exited during start-up, code " + process.ExitCode);
                    // SOLIDWORKS waits for its activation wizard, which nothing here answers, so it
                    // would never register: say so now rather than at the timeout. The catch below
                    // ends the instance, and the wizard goes with the job.
                    Dictionary<string, object> asking = watch != null ? watch.Activation : null;
                    if (asking != null)
                    {
                        Dictionary<string, object> why = new Dictionary<string, object>();
                        why["activation"] = asking;
                        throw new BridgeException("solidworks_not_activated",
                            "SOLIDWORKS needs product activation on this PC: its activation wizard is asking, and SolidSeas " +
                            "never answers it. Activate SOLIDWORKS, then try again.", why);
                    }
                    if (Request.RemainingMs() <= 0)
                        throw new BridgeException("timeout", "SolidWorks_PID_" + process.Id + " did not appear in the Running Object Table in time");
                    Pump.Sleep(Math.Min(250, Request.RemainingMs()));
                }
                sw = found as ISldWorks;
                if (sw == null) throw new BridgeException("start_failed", "SolidWorks_PID_" + process.Id + " is not a SOLIDWORKS application");
                if (watch != null) watch.Registered();
                // Hidden at once, and out of the user's hands, so nobody opens their own work in it.
                sw.Visible = false;
                sw.UserControl = false;
                // StartupProcessCompleted is reported, not waited for: a hidden instance never sets it
                // (measured with SOLIDWORKS 2024 SP1). Calls made while it is still busy starting are
                // retried by the message filter.
                Dictionary<string, object> d = Info();
                d["exe"] = exe;
                d["in_job"] = process.InJob;
                return d;
            }
            catch (Exception e)
            {
                // The dialogs the instance showed while it started say why it did not register.
                List<object> dialogs = watch != null ? watch.DialogsSince(0, 1000) : null;
                EndSolidWorks(5000);
                BridgeException failed = e as BridgeException;
                if (failed == null || dialogs == null || dialogs.Count == 0) throw;
                Dictionary<string, object> details = failed.Details ?? new Dictionary<string, object>();
                details["dialogs"] = dialogs;
                throw new BridgeException(failed.Code, failed.Message, details);
            }
        }

        static Dictionary<string, object> Info()
        {
            ISldWorks app = Require();
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["pid"] = process.Id;
            d["revision"] = app.RevisionNumber();
            d["visible"] = app.Visible;
            d["user_control"] = app.UserControl;
            d["startup_completed"] = app.StartupProcessCompleted;
            d["document_count"] = app.GetDocumentCount();
            List<object> titles = new List<object>();
            object[] open = app.GetDocuments() as object[];
            if (open != null)
            {
                foreach (object o in open)
                {
                    ModelDoc2 doc = o as ModelDoc2;
                    if (doc != null) titles.Add(doc.GetTitle());
                    if (o != null && Marshal.IsComObject(o) && !IsRemembered(o)) Marshal.ReleaseComObject(o);
                }
            }
            d["documents"] = titles;
            d["window_watch"] = watch != null && watch.Running;
            d["windows_hidden"] = watch != null ? watch.Hidden : 0;
            // Read, never set: a SOLIDWORKS user preference shared with every session of this account.
            d["step_ap"] = app.GetUserPreferenceIntegerValue((int)swUserPreferenceIntegerValue_e.swStepAP);
            return d;
        }

        static bool IsRemembered(object o)
        {
            foreach (ModelDoc2 doc in documents.Values)
            {
                if (ReferenceEquals(doc, o)) return true;
            }
            return false;
        }

        static Dictionary<string, object> SolidWorksInfo(Args args)
        {
            args.Allow();
            return Info();
        }

        static Dictionary<string, object> ExitSolidWorks(Args args)
        {
            args.Allow();
            return EndSolidWorks(Math.Max(1000, Request.RemainingMs()), true);
        }

        public static Dictionary<string, object> EndSolidWorks(int waitMs)
        {
            return EndSolidWorks(waitMs, false);
        }

        // Ends the SOLIDWORKS this bridge started. First it closes the documents the bridge opened
        // or created, the only ones it ever closes, and never saves one (they are read-only, or
        // new and never saved), so none of them is still open, changed or not, when the instance
        // ends. Then it terminates the Job Object that holds the instance, which ends that
        // SLDWORKS.exe and whatever it started, and nothing else.
        // SOLIDWORKS' own shutdown, ExitApp, is never used: it rewrites about 230 values under
        // User Interface in the registry the user's session shares (measured with SOLIDWORKS 2024
        // SP1). The swapi README says what ending it this way leaves behind.
        // With keepForeign (exit_solidworks and shutdown), a document the instance shows that the
        // bridge did not open or create is a person's: the instance is not ended but shown to the
        // person, and the request fails with foreign_documents (SolidSeas-1k3). The client asks
        // again once they are closed. The instance is in a kill-on-close job, so a timeout, a
        // crash or the end of the conversation still ends it with them.
        public static Dictionary<string, object> EndSolidWorks(int waitMs, bool keepForeign)
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            if (process == null)
            {
                d["ended"] = "not_started";
                return d;
            }
            d["pid"] = process.Id;
            if (process.HasExited)
            {
                d["ended"] = "already_exited";
            }
            else
            {
                if (sw != null)
                {
                    int closed = 0;
                    foreach (int handle in new List<int>(documents.Keys))
                    {
                        try
                        {
                            Close(handle);
                            closed++;
                        }
                        catch (Exception e) { Console.Error.WriteLine("closing document " + handle + ": " + e.Message); }
                    }
                    d["documents_closed"] = closed;
                    if (keepForeign) KeepForeignDocuments(closed);
                    // A document still open here was not opened by the bridge: one loaded with
                    // another and not shown, or, when the instance is ended without keepForeign,
                    // one a person opened in it. It is never saved, and it goes with the
                    // instance; say so.
                    try
                    {
                        int open = sw.GetDocumentCount();
                        d["documents_open"] = open;
                        if (open > 0) Console.Error.WriteLine("ending SOLIDWORKS with " + open + " document(s) open that the bridge did not open; they are not saved");
                    }
                    catch (Exception e) { Console.Error.WriteLine("GetDocumentCount: " + e.Message); }
                }
                ReleaseApp();
                d["job_processes"] = process.ActiveProcesses;
                if (process.TerminateJob(EndedExitCode))
                {
                    d["ended"] = "job_terminated";
                }
                else
                {
                    // Closing the job below ends what is in it all the same (kill-on-close).
                    d["ended"] = "job_closed";
                    d["reason"] = Native.LastError("TerminateJobObject");
                }
                process.WaitForExit(Math.Max(1000, Math.Min(waitMs, 30000)));
                int start = System.Environment.TickCount;
                while (process.ActiveProcesses > 0 && unchecked(System.Environment.TickCount - start) < 10000) Pump.Sleep(50);
            }
            ReleaseApp();
            documents.Clear();
            watches.Clear();
            process.CloseJob();
            if (watch != null)
            {
                watch.Stop(5000);
                d["windows_hidden"] = watch.Hidden;
                watch = null;
            }
            if (process.HasExited) d["exit_code"] = (long)process.ExitCode;
            process.CloseHandle();
            process = null;
            UnmarkBatch();
            ReleaseInstanceMutex();
            return d;
        }

        static void TakeInstanceMutex()
        {
            Mutex m = new Mutex(false, InstanceMutexName);
            bool owned;
            try { owned = m.WaitOne(0); }
            catch (AbandonedMutexException) { owned = true; } // a bridge that was ended held it
            if (!owned)
            {
                m.Dispose();
                throw new BridgeException("refused", "another SolidSeas bridge is running its own SOLIDWORKS; one at a time");
            }
            instanceMutex = m;
        }

        static void ReleaseInstanceMutex()
        {
            if (instanceMutex == null) return;
            try { instanceMutex.ReleaseMutex(); }
            catch (ApplicationException) { }
            instanceMutex.Dispose();
            instanceMutex = null;
        }

        // The titles of the documents the instance shows that this bridge did not open or create:
        // a person opened them in the seconds before the instance was hidden, or a double-click
        // reached it. A document loaded with another, such as an assembly's component, is not
        // shown (IModelDoc2.Visible is false) and does not count.
        static List<object> ForeignDocuments()
        {
            List<object> titles = new List<object>();
            object[] open = sw.GetDocuments() as object[];
            if (open == null) return titles;
            foreach (object o in open)
            {
                ModelDoc2 doc = o as ModelDoc2;
                bool ours = IsRemembered(o);
                if (doc != null && !ours && doc.Visible) titles.Add(doc.GetTitle());
                if (o != null && Marshal.IsComObject(o) && !ours) Marshal.ReleaseComObject(o);
            }
            return titles;
        }

        // Refuses to end the instance while it shows a document the bridge did not open or create,
        // and shows the instance to the person, who can save and close the documents there
        // (SolidSeas-1k3). The bridge's own documents are closed by then.
        static void KeepForeignDocuments(int closed)
        {
            List<object> foreign = ForeignDocuments();
            if (foreign.Count == 0) return;
            sw.Visible = true;
            sw.UserControl = true;
            Console.Error.WriteLine("not ending SOLIDWORKS: it shows " + foreign.Count +
                " document(s) the bridge did not open; it is shown so they can be saved and closed");
            Dictionary<string, object> details = new Dictionary<string, object>();
            details["documents"] = foreign;
            details["documents_closed"] = closed;
            details["shown"] = true;
            throw new BridgeException("foreign_documents", "SOLIDWORKS shows " + foreign.Count +
                " document(s) SolidSeas did not open; it is shown so they can be saved and closed, and it ends " +
                "when asked again once they are", details);
        }

        static void ReleaseApp()
        {
            foreach (PartWatch w in watches.Values)
            {
                try { w.Stop(); }
                catch (Exception) { }
            }
            watches.Clear();
            foreach (ModelDoc2 doc in documents.Values)
            {
                try { Marshal.ReleaseComObject(doc); }
                catch (Exception) { }
            }
            documents.Clear();
            if (sw != null)
            {
                try { Marshal.FinalReleaseComObject(sw); }
                catch (Exception) { }
                sw = null;
            }
        }

        static int Remember(ModelDoc2 doc)
        {
            int handle = nextHandle++;
            documents[handle] = doc;
            return handle;
        }

        static ModelDoc2 Document(Args args, out int handle)
        {
            Require();
            handle = args.Int("doc", 0, 1, int.MaxValue);
            ModelDoc2 doc;
            if (!documents.TryGetValue(handle, out doc))
                throw new BridgeException("not_found", "no document " + handle + " opened or created by this bridge");
            return doc;
        }

        static string TypeName(int type)
        {
            switch (type)
            {
                case (int)swDocumentTypes_e.swDocPART: return "part";
                case (int)swDocumentTypes_e.swDocASSEMBLY: return "assembly";
                case (int)swDocumentTypes_e.swDocDRAWING: return "drawing";
                default: return "other";
            }
        }

        static Dictionary<string, object> Describe(int handle)
        {
            ModelDoc2 doc = documents[handle];
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["doc"] = handle;
            d["title"] = doc.GetTitle();
            d["path"] = doc.GetPathName();
            d["type"] = TypeName(doc.GetType());
            d["read_only"] = doc.IsOpenedReadOnly();
            d["dirty"] = doc.GetSaveFlag();
            Configuration active = doc.ConfigurationManager == null ? null : doc.ConfigurationManager.ActiveConfiguration;
            d["active_configuration"] = active == null ? null : active.Name;
            string[] names = doc.GetConfigurationNames() as string[];
            d["configurations"] = names ?? new string[0];
            d["feature_count"] = doc.GetFeatureCount();
            d["watched"] = watches.ContainsKey(handle);
            return d;
        }

        // The names of the bits set in a SOLIDWORKS error or warning code, from the enumeration
        // the API documents for it; a bit without a name is given as a number.
        static List<object> FlagNames(Type flags, int value)
        {
            List<object> names = new List<object>();
            for (int bit = 0; bit < 31; bit++)
            {
                int mask = 1 << bit;
                if ((value & mask) == 0) continue;
                string name = Enum.GetName(flags, mask);
                names.Add(name ?? mask.ToString());
            }
            return names;
        }

        // NewDocument hands the instance to the user (UserControl becomes true, measured with
        // SOLIDWORKS 2024 SP1), so it is taken back after every call that creates or opens one.
        static void KeepHidden(ISldWorks app)
        {
            if (app.UserControl) app.UserControl = false;
            if (app.Visible) app.Visible = false;
        }

        // Hidden again a moment later too: alone (no other SOLIDWORKS running), the frame
        // showed after a new document even though it was hidden right after NewDocument
        // returned (SolidSeas-okg, measured 2026-10-14), so SOLIDWORKS can show it late.
        static void KeepHiddenSettled(ISldWorks app)
        {
            KeepHidden(app);
            for (int i = 0; i < 3; i++)
            {
                System.Threading.Thread.Sleep(100);
                KeepHidden(app);
            }
        }

        // NewDocument, then the frame hidden as well. New documents are not hidden through
        // ISldWorks' DocumentVisible: with it they stayed hidden, but InsertImportedComponent faulted
        // (RPC_E_SERVERFAULT), STEP inserts stopped behind Open Progress and a new part was
        // not the active document live mode builds in (measured 2026-10-15, SolidSeas-okg).
        static ModelDoc2 NewDocumentHidden(ISldWorks app, string template)
        {
            try
            {
                return app.NewDocument(template, 0, 0, 0) as ModelDoc2;
            }
            finally
            {
                KeepHiddenSettled(app);
            }
        }

        static Dictionary<string, object> NewDocument(Args args)
        {
            args.Allow("template");
            ISldWorks app = Require();
            string template = args.FullPath("template");
            string ext = Path.GetExtension(template).ToLowerInvariant();
            if (ext != ".prtdot" && ext != ".asmdot" && ext != ".drwdot")
                throw new BridgeException("invalid_argument", "template must be a .prtdot, .asmdot or .drwdot file");
            if (!File.Exists(template)) throw new BridgeException("not_found", "template not found: " + template);
            ModelDoc2 doc = NewDocumentHidden(app, template);
            if (doc == null) throw new BridgeException("new_failed", "NewDocument returned no document for " + template);
            return Describe(Remember(doc));
        }

        static Dictionary<string, object> OpenDocument(Args args)
        {
            args.Allow("path", "read_only", "configuration", "allow_network");
            ISldWorks app = Require();
            string path = args.FullPath("path", args.Bool("allow_network", false));
            // Opened for writing, SOLIDWORKS puts a ~$ lock file next to the document, and an
            // instance ended after a timeout leaves it there. Nothing needs writing yet.
            if (!args.Bool("read_only", true))
                throw new BridgeException("refused", "documents are opened read-only; opening one for writing is not offered");
            string configuration = args.String("configuration", "");
            int type;
            switch (Path.GetExtension(path).ToLowerInvariant())
            {
                case ".sldprt": type = (int)swDocumentTypes_e.swDocPART; break;
                case ".sldasm": type = (int)swDocumentTypes_e.swDocASSEMBLY; break;
                case ".slddrw": type = (int)swDocumentTypes_e.swDocDRAWING; break;
                default: throw new BridgeException("invalid_argument", "only .sldprt, .sldasm and .slddrw documents are opened");
            }
            if (!File.Exists(path)) throw new BridgeException("not_found", "no such file: " + path);
            // A document already open here was not opened by this request (a component another
            // document loaded, for example): never touch it.
            if (app.GetOpenDocumentByName(path) != null)
                throw new BridgeException("refused", "already open in this SOLIDWORKS instance; not touched");
            int options = (int)swOpenDocOptions_e.swOpenDocOptions_Silent | (int)swOpenDocOptions_e.swOpenDocOptions_ReadOnly;
            // An assembly opens with its components resolved whatever the account's lightweight
            // option says (read, never set): a per-call flag, so mass_properties sees their bodies.
            // Opened with these flags, the harness saw SOLIDWORKS write briefly in the assembly's
            // folder (its time changed, its entries did not); the README lists it as a side effect.
            if (type == (int)swDocumentTypes_e.swDocASSEMBLY)
                options |= (int)swOpenDocOptions_e.swOpenDocOptions_OverrideDefaultLoadLightweight;
            int errors = 0, warnings = 0;
            ModelDoc2 doc = app.OpenDoc6(path, type, options, configuration, ref errors, ref warnings) as ModelDoc2;
            if (doc == null)
            {
                Dictionary<string, object> details = new Dictionary<string, object>();
                details["errors"] = errors;
                details["warnings"] = warnings;
                details["error_names"] = FlagNames(typeof(swFileLoadError_e), errors);
                details["warning_names"] = FlagNames(typeof(swFileLoadWarning_e), warnings);
                throw new BridgeException("open_failed", "OpenDoc6 failed for " + path, details);
            }
            KeepHidden(app);
            Dictionary<string, object> d = Describe(Remember(doc));
            d["errors"] = errors;
            d["warnings"] = warnings;
            if (warnings != 0) d["warning_names"] = FlagNames(typeof(swFileLoadWarning_e), warnings);
            return d;
        }

        static Dictionary<string, object> DocumentInfo(Args args)
        {
            args.Allow("doc");
            int handle;
            Document(args, out handle);
            return Describe(handle);
        }

        static Dictionary<string, object> ListFeatures(Args args)
        {
            args.Allow("doc", "limit");
            int handle;
            ModelDoc2 doc = Document(args, out handle);
            int limit = args.Int("limit", 10000, 1, 100000);
            List<object> features = new List<object>();
            Feature feature = doc.FirstFeature() as Feature;
            while (feature != null && features.Count < limit)
            {
                Dictionary<string, object> f = new Dictionary<string, object>();
                f["name"] = feature.Name;
                f["type"] = feature.GetTypeName2();
                f["id"] = feature.GetID();
                features.Add(f);
                Feature next = feature.GetNextFeature() as Feature;
                Marshal.ReleaseComObject(feature);
                feature = next;
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["doc"] = handle;
            d["features"] = features;
            d["truncated"] = feature != null;
            if (feature != null) Marshal.ReleaseComObject(feature);
            return d;
        }

        static Dictionary<string, object> SaveCopy(Args args)
        {
            args.Allow("doc", "path", "overwrite", "allow_network");
            int handle;
            ModelDoc2 doc = Document(args, out handle);
            string target = args.FullPath("path", args.Bool("allow_network", false));
            bool overwrite = args.Bool("overwrite", false);
            string ext = Path.GetExtension(target).ToLowerInvariant();
            if (Array.IndexOf(SaveExtensions, ext) < 0)
                throw new BridgeException("invalid_argument", "SaveAs3 writes the format the extension names; allowed: " + string.Join(" ", SaveExtensions));
            string own = doc.GetPathName();
            if (!string.IsNullOrEmpty(own) && string.Equals(Path.GetFullPath(own), target, StringComparison.OrdinalIgnoreCase))
                throw new BridgeException("refused", "a document is never saved over its own file");
            string folder = Path.GetDirectoryName(target);
            if (folder == null || !Directory.Exists(folder)) throw new BridgeException("not_found", "no such folder: " + folder);
            if (Directory.Exists(target)) throw new BridgeException("refused", "a folder has that name: " + target);
            bool existed = File.Exists(target);
            if (existed)
            {
                // Another name for an open document's file (a junction, a hard link, a mapped
                // drive, a short name) passes the comparison above: compare the files themselves.
                // Measured: SaveAs3 to a STEP name hard-linked to the open part emptied the part.
                string identity = Native.FileIdentity(target);
                if (identity == null)
                    throw new BridgeException("refused", "cannot tell which file " + target + " is, so it is not replaced");
                string clash = OpenDocumentFile(identity);
                if (clash != null)
                    throw new BridgeException("refused", "a document is never saved over its own file: " + target + " is the file of " + clash);
            }
            if (existed && !overwrite) throw new BridgeException("refused", "output exists; pass overwrite to replace it");
            DateTime before = existed ? File.GetLastWriteTimeUtc(target) : DateTime.MinValue;
            // SOLIDWORKS writes a .gltf into a folder named after the file (its name lowercased,
            // measured 2026-10-14), with the .bin beside it: <folder>\<name>\<name>.gltf. That
            // folder is part of the output, so an existing one is replaced only with overwrite.
            string gltfFolder = ext == ".gltf" ? Path.Combine(folder, Path.GetFileNameWithoutExtension(target)) : null;
            if (gltfFolder != null && Directory.Exists(gltfFolder) && !overwrite)
                throw new BridgeException("refused", "output exists (SOLIDWORKS writes a .gltf into the folder " + gltfFolder +
                    "); pass overwrite to replace it");
            DateTime started = DateTime.UtcNow.AddSeconds(-2);

            int errors = 0, warnings = 0;
            int options = (int)swSaveAsOptions_e.swSaveAsOptions_Silent | (int)swSaveAsOptions_e.swSaveAsOptions_Copy;
            bool ok = doc.Extension.SaveAs3(target, (int)swSaveAsVersion_e.swSaveAsCurrentVersion, options, null, null,
                                            ref errors, ref warnings);
            bool written = File.Exists(target) && (!existed || File.GetLastWriteTimeUtc(target) != before);
            string gltfWritten = null;
            if (!written && gltfFolder != null && Directory.Exists(gltfFolder))
            {
                foreach (string f in Directory.GetFiles(gltfFolder, "*.gltf"))
                {
                    if (File.GetLastWriteTimeUtc(f) >= started) gltfWritten = f;
                }
                written = gltfWritten != null;
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["errors"] = errors;
            d["warnings"] = warnings;
            if (errors != 0) d["error_names"] = FlagNames(typeof(swFileSaveError_e), errors);
            if (warnings != 0) d["warning_names"] = FlagNames(typeof(swFileSaveWarning_e), warnings);
            if (!ok || !written)
                throw new BridgeException("save_failed", ok ? "SaveAs3 reported success but wrote no file" : "SaveAs3 failed", d);
            d["doc"] = handle;
            if (gltfWritten != null)
            {
                // The .gltf in its folder, and every file SOLIDWORKS wrote there with it.
                d["path"] = gltfWritten;
                List<string> files = new List<string>();
                long bytes = 0;
                foreach (string f in Directory.GetFiles(Path.GetDirectoryName(gltfWritten)))
                {
                    if (File.GetLastWriteTimeUtc(f) < started) continue;
                    files.Add(f);
                    bytes += new FileInfo(f).Length;
                }
                d["files"] = files;
                d["bytes"] = bytes;
                return d;
            }
            // SOLIDWORKS may change the name's case (it writes .STL, and o02_boxa.glb for
            // o02_boxA.glb): report the name on disk.
            string[] onDisk = Directory.GetFiles(folder, Path.GetFileName(target));
            d["path"] = onDisk.Length == 1 ? onDisk[0] : target;
            d["bytes"] = new FileInfo(target).Length;
            if (ext == ".step" || ext == ".stp")
                d["step_ap"] = sw.GetUserPreferenceIntegerValue((int)swUserPreferenceIntegerValue_e.swStepAP);
            return d;
        }

        // The path of a document open in this SOLIDWORKS (one the bridge opened, or one loaded
        // with it) whose file is the file identified, or null.
        static string OpenDocumentFile(string identity)
        {
            List<string> paths = new List<string>();
            foreach (ModelDoc2 doc in documents.Values) paths.Add(doc.GetPathName());
            object[] open = sw.GetDocuments() as object[];
            if (open != null)
            {
                foreach (object o in open)
                {
                    ModelDoc2 doc = o as ModelDoc2;
                    if (doc != null) paths.Add(doc.GetPathName());
                    if (o != null && Marshal.IsComObject(o) && !IsRemembered(o)) Marshal.ReleaseComObject(o);
                }
            }
            foreach (string path in paths)
            {
                if (!string.IsNullOrEmpty(path) && Native.FileIdentity(path) == identity) return path;
            }
            return null;
        }

        static Dictionary<string, object> CloseDocument(Args args)
        {
            args.Allow("doc");
            int handle;
            Document(args, out handle);
            string title = Close(handle);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["doc"] = handle;
            d["title"] = title;
            d["closed"] = true;
            return d;
        }

        static string Close(int handle)
        {
            ModelDoc2 doc = documents[handle];
            string title = doc.GetTitle();
            // A watched part reports its own DestroyNotify2 while CloseDoc runs; the watch is
            // dropped afterwards, when the document may already be gone.
            sw.CloseDoc(title);
            documents.Remove(handle);
            PartWatch watch;
            if (watches.TryGetValue(handle, out watch))
            {
                watches.Remove(handle);
                try { watch.Stop(); }
                catch (Exception) { }
            }
            Marshal.ReleaseComObject(doc);
            return title;
        }

        static Dictionary<string, object> WatchDocument(Args args)
        {
            args.Allow("doc");
            int handle;
            ModelDoc2 doc = Document(args, out handle);
            PartDoc part = doc as PartDoc;
            if (part == null) throw new BridgeException("invalid_argument", "only parts can be watched");
            if (!watches.ContainsKey(handle)) watches[handle] = new PartWatch(handle, part);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["doc"] = handle;
            d["events"] = PartWatch.Names;
            return d;
        }

        static Dictionary<string, object> UnwatchDocument(Args args)
        {
            args.Allow("doc");
            int handle;
            Document(args, out handle);
            PartWatch watch;
            bool was = watches.TryGetValue(handle, out watch);
            if (was)
            {
                watch.Stop();
                watches.Remove(handle);
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["doc"] = handle;
            d["was_watched"] = was;
            return d;
        }
    }
}
