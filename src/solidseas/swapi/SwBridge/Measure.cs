// mass_properties: what SOLIDWORKS measures of a document the bridge opened or created.
//
// The measures, and what they cover, are those of the read-only measuring harness that
// produced the truth for the fixtures and the corpus with SOLIDWORKS 2024 SP1 (2026-10-04),
// and what it learned is kept here:
// - Mass, volume, surface area and centre of mass come from IMassProperty2, with its defaults
//   (hidden bodies and components left out, SI units). A part whose bodies are all sheets gets
//   no IMassProperty2 at all; the older IMassProperty then reports 0, and "api" says which one
//   answered. Use sheet_area_m2 for sheets.
// - IMassProperty2 returned 0 for parts with a visible solid (two corpus parts saved by
//   SOLIDWORKS 2016, no open warnings), while the import of their own STEP measured normal
//   values: a silent failure, reported as mass_zero_with_visible_solids and valid false.
// - Body counts include hidden bodies; topology, Check3, the sheet area and bbox_m cover the
//   visible bodies, the set IMassProperty2 covers. Hidden part bodies are those GetBodies2 lists
//   with hidden ones and without; in an assembly, bodies of hidden components or hidden in
//   their part.
// - The boxes are precise: IBody2.GetExtremePoint along the six axis directions. Component2
//   GetBodies3 returns bodies in the part's own coordinates, so each is copied and moved by the
//   component's Transform2 first. PartDoc.GetPartBox and AssemblyDoc.GetBox are coarser (o16:
//   0.13484 m against 0.12137 m) and are given as api_box_m.
// - Suppressed, envelope and unresolved components are left out of every body measure; an
//   assembly the bridge opens has its components resolved (OpenDocument).
// Another configuration is measured by showing it (ShowConfiguration2) and the active one is
// shown again afterwards: the document is never saved, but SOLIDWORKS marks it changed while
// another configuration shows. Nothing is rebuilt, selected or set, the mass property object
// included: its override options are read only.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace SolidSeas.SwBridge
{
    static partial class Operations
    {
        const int DefaultMaxConfigurations = 50;

        // One body of the document: its transform into the document's coordinates (null in a
        // part), whether it is a sheet, whether it is visible (measured), and its box once read.
        sealed class BodyRef
        {
            public Body2 Body;
            public MathTransform Transform;
            public bool Sheet;
            public bool Visible;
            public double[] Box;
        }

        static Dictionary<string, object> MassProperties(Args args)
        {
            args.Allow("doc", "configuration", "all_configurations", "max_configurations");
            string wanted = args.String("configuration", null);
            bool all = args.Bool("all_configurations", false);
            int max = args.Int("max_configurations", DefaultMaxConfigurations, 1, 1000);
            if (wanted != null && wanted.Length == 0) throw new BridgeException("invalid_argument", "configuration is empty");
            if (wanted != null && all) throw new BridgeException("invalid_argument", "give configuration or all_configurations, not both");
            int handle;
            ModelDoc2 doc = Document(args, out handle);
            int type = doc.GetType();
            if (type != (int)swDocumentTypes_e.swDocPART && type != (int)swDocumentTypes_e.swDocASSEMBLY)
                throw new BridgeException("invalid_argument", "mass properties are measured for parts and assemblies");
            string[] names = doc.GetConfigurationNames() as string[] ?? new string[0];
            Configuration current = doc.ConfigurationManager == null ? null : doc.ConfigurationManager.ActiveConfiguration;
            string active = current == null ? null : current.Name;
            List<string> order = new List<string>();
            if (all)
            {
                for (int i = 0; i < names.Length && i < max; i++) order.Add(names[i]);
            }
            else if (wanted != null)
            {
                if (Array.IndexOf(names, wanted) < 0) throw new BridgeException("not_found", "no configuration named " + wanted);
                order.Add(wanted);
            }
            else
            {
                order.Add(active);
            }

            List<object> measures = new List<object>();
            bool switched = false;
            object restored = null;
            try
            {
                foreach (string name in order)
                {
                    Dictionary<string, object> m;
                    // Once another configuration was shown, the active one is shown again too.
                    bool show = name != null && (name != active || switched);
                    if (show)
                    {
                        switched = true;
                        if (!doc.ShowConfiguration2(name))
                        {
                            m = new Dictionary<string, object>();
                            m["configuration"] = name;
                            m["active"] = name == active;
                            m["shown"] = false;
                            measures.Add(m);
                            continue;
                        }
                    }
                    m = Measure(doc);
                    m["configuration"] = name;
                    m["active"] = name == active;
                    m["shown"] = show;
                    measures.Add(m);
                }
            }
            finally
            {
                if (switched && active != null)
                {
                    try { restored = doc.ShowConfiguration2(active); }
                    catch (Exception e)
                    {
                        Console.Error.WriteLine("mass_properties: showing " + active + " again: " + e.Message);
                        restored = false;
                    }
                }
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["doc"] = handle;
            d["type"] = TypeName(type);
            d["units"] = "SI";
            d["active_configuration"] = active;
            d["configurations"] = names;
            d["measures"] = measures;
            if (switched) d["restored_active_configuration"] = restored;
            if (all && names.Length > max) d["configurations_skipped"] = names.Length - max;
            d["dirty"] = doc.GetSaveFlag();
            return d;
        }

        // The measures of the configuration showing now (SI units: m, m^2, m^3, kg).
        static Dictionary<string, object> Measure(ModelDoc2 doc)
        {
            Stopwatch t = Stopwatch.StartNew();
            Dictionary<string, object> m = new Dictionary<string, object>();
            List<object> warnings = new List<object>();
            List<BodyRef> bodies = new List<BodyRef>();
            double[] apiBox = null;
            int solids = 0, sheets = 0, hiddenSolids = 0, hiddenSheets = 0;
            bool hiddenIdentified = true;
            Dictionary<string, object> assembly = null;
            if (doc.GetType() == (int)swDocumentTypes_e.swDocPART)
            {
                PartDoc part = (PartDoc)doc;
                object[] allSolid = part.GetBodies2((int)swBodyType_e.swSolidBody, false) as object[];
                object[] allSheet = part.GetBodies2((int)swBodyType_e.swSheetBody, false) as object[];
                object[] visibleSolid = part.GetBodies2((int)swBodyType_e.swSolidBody, true) as object[];
                object[] visibleSheet = part.GetBodies2((int)swBodyType_e.swSheetBody, true) as object[];
                AddBodies(visibleSolid, bodies, null, false, true, false);
                AddBodies(visibleSheet, bodies, null, true, true, false);
                solids = Count(allSolid);
                sheets = Count(allSheet);
                hiddenSolids = solids - Count(visibleSolid);
                hiddenSheets = sheets - Count(visibleSheet);
                if (hiddenSolids > 0 || hiddenSheets > 0)
                {
                    int foundSolid = AddHidden(allSolid, bodies, false), foundSheet = AddHidden(allSheet, bodies, true);
                    hiddenIdentified = foundSolid == hiddenSolids && foundSheet == hiddenSheets;
                }
                try { apiBox = part.GetPartBox(true) as double[]; }
                catch (COMException) { }
            }
            else
            {
                AssemblyDoc asm = (AssemblyDoc)doc;
                assembly = Components(doc, asm, bodies);
                foreach (BodyRef b in bodies)
                {
                    if (b.Sheet) { sheets++; if (!b.Visible) hiddenSheets++; }
                    else { solids++; if (!b.Visible) hiddenSolids++; }
                }
                try { apiBox = asm.GetBox(0) as double[]; }
                catch (COMException) { }
                object light = assembly["lightweight_components"];
                if (light is int && (int)light > 0) warnings.Add("lightweight_components");
                if ((int)assembly["unresolved"] > 0) warnings.Add("unresolved_components");
            }
            m["solid_bodies"] = solids;
            m["sheet_bodies"] = sheets;
            m["hidden_solid_bodies"] = hiddenSolids;
            m["hidden_sheet_bodies"] = hiddenSheets;
            if (!hiddenIdentified)
            {
                m["hidden_bodies_identified"] = false;
                warnings.Add("hidden_bodies_not_identified");
            }
            if (assembly != null) m["assembly"] = assembly;
            m["solid_topology"] = Topology(bodies, false);
            m["sheet_topology"] = Topology(bodies, true);
            m["check3"] = Faults(bodies);
            m["sheet_area_m2"] = SheetArea(bodies);

            int boxErrors = 0;
            foreach (BodyRef b in bodies)
            {
                try { if (!Extents(b)) boxErrors++; }
                catch (COMException) { boxErrors++; }
            }
            m["bbox_m"] = Union(bodies, delegate(BodyRef b) { return b.Visible; });
            m["bbox_solids_m"] = Union(bodies, delegate(BodyRef b) { return b.Visible && !b.Sheet; });
            m["bbox_all_bodies_m"] = hiddenIdentified ? Union(bodies, delegate(BodyRef b) { return true; }) : null;
            m["bbox_method"] = "IBody2.GetExtremePoint";
            m["bbox_errors"] = boxErrors;
            if (boxErrors > 0) warnings.Add("bbox_errors");
            m["api_box_m"] = apiBox;

            Dictionary<string, object> mass = Mass(doc);
            int visibleSolids = solids - hiddenSolids;
            object volume;
            mass.TryGetValue("volume_m3", out volume);
            bool valid = (string)mass["api"] == "IMassProperty2" && visibleSolids > 0 && volume is double && (double)volume > 0;
            if (visibleSolids == 0) warnings.Add("no_visible_solids");
            else if (volume is double && (double)volume == 0) warnings.Add("mass_zero_with_visible_solids");
            object units;
            if (mass.TryGetValue("use_system_units", out units) && units is bool && !(bool)units)
            {
                valid = false;
                warnings.Add("not_si_units");
            }
            object overridden;
            if (mass.TryGetValue("overrides", out overridden) && overridden is Dictionary<string, object>)
            {
                foreach (KeyValuePair<string, object> o in (Dictionary<string, object>)overridden)
                {
                    if (o.Value is bool && (bool)o.Value) warnings.Add(o.Key + "_overridden");
                }
            }
            mass["valid"] = valid;
            m["mass"] = mass;
            m["warnings"] = warnings;
            m["seconds"] = Math.Round(t.Elapsed.TotalSeconds, 3);
            return m;
        }

        static int Count(object[] a)
        {
            return a == null ? 0 : a.Length;
        }

        static void AddBodies(object list, List<BodyRef> into, MathTransform transform, bool sheet, bool visible, bool askBody)
        {
            object[] found = list as object[];
            if (found == null) return;
            foreach (object o in found)
            {
                Body2 body = o as Body2;
                if (body == null) continue;
                bool shown = visible;
                if (shown && askBody)
                {
                    try { shown = body.Visible; }
                    catch (COMException) { }
                }
                BodyRef b = new BodyRef();
                b.Body = body;
                b.Transform = transform;
                b.Sheet = sheet;
                b.Visible = shown;
                into.Add(b);
            }
        }

        // The hidden bodies of a part: those in the list with hidden bodies whose IBody2.Visible is false.
        static int AddHidden(object[] all, List<BodyRef> into, bool sheet)
        {
            int n = 0;
            if (all == null) return 0;
            foreach (object o in all)
            {
                Body2 body = o as Body2;
                if (body == null) continue;
                bool shown;
                try { shown = body.Visible; }
                catch (COMException) { continue; }
                if (shown) continue;
                BodyRef b = new BodyRef();
                b.Body = body;
                b.Sheet = sheet;
                b.Visible = false;
                into.Add(b);
                n++;
            }
            return n;
        }

        // The bodies of every resolved part component, at every level, moved into the assembly's
        // coordinates when their boxes are read; and counts of what was left out, and why.
        static Dictionary<string, object> Components(ModelDoc2 doc, AssemblyDoc asm, List<BodyRef> bodies)
        {
            int components = 0, suppressed = 0, envelopes = 0, parts = 0, unresolved = 0, subassemblies = 0;
            int under = 0, elsewhere = 0, virtuals = 0, hidden = 0;
            string own = doc.GetPathName();
            string folder = string.IsNullOrEmpty(own) ? null : System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(own)) + "\\";
            object[] list = asm.GetComponents(false) as object[];
            if (list != null)
            {
                foreach (object o in list)
                {
                    Component2 c = o as Component2;
                    if (c == null) continue;
                    components++;
                    try
                    {
                        if (c.IsVirtual) virtuals++;
                        string path = c.GetPathName();
                        if (folder != null && !string.IsNullOrEmpty(path))
                        {
                            if (System.IO.Path.GetFullPath(path).StartsWith(folder, StringComparison.OrdinalIgnoreCase)) under++;
                            else elsewhere++;
                        }
                    }
                    catch (COMException) { }
                    catch (ArgumentException) { }
                    catch (NotSupportedException) { }
                    catch (System.IO.IOException) { }
                    if (c.IsSuppressed()) { suppressed++; continue; }
                    if (c.IsEnvelope()) { envelopes++; continue; }
                    ModelDoc2 model = c.GetModelDoc2() as ModelDoc2;
                    if (model == null) { unresolved++; continue; }
                    if (model.GetType() != (int)swDocumentTypes_e.swDocPART) { subassemblies++; continue; }
                    parts++;
                    bool shown = !ComponentHidden(c);
                    if (!shown) hidden++;
                    MathTransform transform = c.Transform2;
                    object info;
                    AddBodies(c.GetBodies3((int)swBodyType_e.swSolidBody, out info), bodies, transform, false, shown, true);
                    AddBodies(c.GetBodies3((int)swBodyType_e.swSheetBody, out info), bodies, transform, true, shown, true);
                }
            }
            Dictionary<string, object> a = new Dictionary<string, object>();
            a["components"] = components;
            a["suppressed"] = suppressed;
            a["envelopes"] = envelopes;
            a["part_components"] = parts;
            a["hidden_part_components"] = hidden;
            a["subassemblies"] = subassemblies;
            a["unresolved"] = unresolved;
            a["virtual"] = virtuals;
            a["paths_under_document_folder"] = under;
            a["paths_elsewhere"] = elsewhere;
            try { a["lightweight_components"] = asm.GetLightWeightComponentCount(); }
            catch (COMException) { a["lightweight_components"] = null; }
            return a;
        }

        // A component is hidden when it, or an assembly it is in, is hidden.
        static bool ComponentHidden(Component2 c)
        {
            Component2 current = c;
            for (int guard = 0; current != null && guard < 64; guard++)
            {
                try
                {
                    if (current.Visible == (int)swComponentVisibilityState_e.swComponentHidden) return true;
                    current = current.GetParent();
                }
                catch (COMException) { return false; }
            }
            return false;
        }

        // The body's extents [min x, min y, min z, max x, max y, max z] from IBody2.GetExtremePoint;
        // a component's body is copied into a temporary body and moved by the component's transform.
        static bool Extents(BodyRef b)
        {
            Body2 body = b.Body;
            Body2 copy = null;
            try
            {
                if (b.Transform != null)
                {
                    copy = body.Copy() as Body2;
                    if (copy == null || !copy.ApplyTransform(b.Transform)) return false;
                    body = copy;
                }
                double x, y, z;
                double[] e = new double[6];
                if (!body.GetExtremePoint(-1, 0, 0, out x, out y, out z)) return false;
                e[0] = x;
                if (!body.GetExtremePoint(0, -1, 0, out x, out y, out z)) return false;
                e[1] = y;
                if (!body.GetExtremePoint(0, 0, -1, out x, out y, out z)) return false;
                e[2] = z;
                if (!body.GetExtremePoint(1, 0, 0, out x, out y, out z)) return false;
                e[3] = x;
                if (!body.GetExtremePoint(0, 1, 0, out x, out y, out z)) return false;
                e[4] = y;
                if (!body.GetExtremePoint(0, 0, 1, out x, out y, out z)) return false;
                e[5] = z;
                b.Box = e;
                return true;
            }
            finally
            {
                if (copy != null) Marshal.ReleaseComObject(copy);
            }
        }

        static double[] Union(List<BodyRef> bodies, Predicate<BodyRef> take)
        {
            double[] box = null;
            foreach (BodyRef b in bodies)
            {
                if (b.Box == null || !take(b)) continue;
                if (box == null)
                {
                    box = (double[])b.Box.Clone();
                    continue;
                }
                for (int i = 0; i < 3; i++) box[i] = Math.Min(box[i], b.Box[i]);
                for (int i = 3; i < 6; i++) box[i] = Math.Max(box[i], b.Box[i]);
            }
            return box;
        }

        static Dictionary<string, object> Topology(List<BodyRef> bodies, bool sheet)
        {
            long faces = 0, edges = 0, vertices = 0;
            foreach (BodyRef b in bodies)
            {
                if (!b.Visible || b.Sheet != sheet) continue;
                faces += b.Body.GetFaceCount();
                edges += b.Body.GetEdgeCount();
                vertices += b.Body.GetVertexCount();
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["faces"] = faces;
            d["edges"] = edges;
            d["vertices"] = vertices;
            return d;
        }

        // IBody2.Check3 of every visible body: how many faults, in how many bodies, by error code.
        static Dictionary<string, object> Faults(List<BodyRef> bodies)
        {
            long total = 0;
            int withFaults = 0, checkErrors = 0;
            SortedDictionary<int, int> codes = new SortedDictionary<int, int>();
            foreach (BodyRef b in bodies)
            {
                if (!b.Visible) continue;
                try
                {
                    FaultEntity faults = b.Body.Check3;
                    int n = faults == null ? 0 : faults.Count;
                    total += n;
                    if (n > 0) withFaults++;
                    for (int i = 0; i < n; i++)
                    {
                        int code = faults.get_ErrorCode(i);
                        int before;
                        codes.TryGetValue(code, out before);
                        codes[code] = before + 1;
                    }
                }
                catch (COMException) { checkErrors++; }
            }
            Dictionary<string, object> byCode = new Dictionary<string, object>();
            foreach (KeyValuePair<int, int> kv in codes) byCode[kv.Key.ToString(CultureInfo.InvariantCulture)] = kv.Value;
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["faults"] = total;
            d["bodies_with_faults"] = withFaults;
            d["fault_codes"] = byCode;
            d["check_errors"] = checkErrors;
            return d;
        }

        // The area of the visible sheets: the sum of IFace2.GetArea.
        static double SheetArea(List<BodyRef> bodies)
        {
            double area = 0;
            foreach (BodyRef b in bodies)
            {
                if (!b.Visible || !b.Sheet) continue;
                object[] faces = b.Body.GetFaces() as object[];
                if (faces == null) continue;
                foreach (object o in faces)
                {
                    Face2 f = o as Face2;
                    if (f != null) area += f.GetArea();
                }
            }
            return area;
        }

        // IMassProperty2 with its defaults, read and never set; IMassProperty when SOLIDWORKS
        // gives no IMassProperty2 (a part whose bodies are all sheets, or no body at all).
        static Dictionary<string, object> Mass(ModelDoc2 doc)
        {
            Dictionary<string, object> m = new Dictionary<string, object>();
            IMassProperty2 mp = null;
            try { mp = doc.Extension.CreateMassProperty2() as IMassProperty2; }
            catch (COMException e) { m["mass_property2_error"] = e.ErrorCode; }
            if (mp != null)
            {
                m["api"] = "IMassProperty2";
                m["volume_m3"] = mp.Volume;
                m["surface_area_m2"] = mp.SurfaceArea;
                m["center_of_mass_m"] = mp.CenterOfMass as double[];
                m["mass_kg"] = mp.Mass;
                m["density_kg_m3"] = mp.Density;
                m["include_hidden"] = mp.IncludeHiddenBodiesOrComponents;
                m["use_system_units"] = mp.UseSystemUnits;
                m["accuracy_level"] = mp.AccuracyLevel;
                Dictionary<string, object> overrides = new Dictionary<string, object>();
                try
                {
                    IMassPropertyOverrideOptions o = mp.GetOverrideOptions() as IMassPropertyOverrideOptions;
                    if (o != null)
                    {
                        overrides["mass"] = o.OverrideMass;
                        overrides["center_of_mass"] = o.OverrideCenterOfMass;
                        overrides["moments_of_inertia"] = o.OverrideMomentsOfInertia;
                    }
                }
                catch (COMException) { }
                m["overrides"] = overrides;
                return m;
            }
            MassProperty old = doc.Extension.CreateMassProperty();
            if (old == null)
            {
                m["api"] = "none";
                return m;
            }
            m["api"] = "IMassProperty";
            m["volume_m3"] = old.Volume;
            m["surface_area_m2"] = old.SurfaceArea;
            m["center_of_mass_m"] = old.CenterOfMass as double[];
            m["mass_kg"] = old.Mass;
            return m;
        }
    }
}
