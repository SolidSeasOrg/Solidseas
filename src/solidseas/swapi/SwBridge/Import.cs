// import_file: a STEP, IGES or Parasolid file imported into a new document of SolidSeas' own
// SOLIDWORKS, with no option changed.
//
// Two ways, named by the request:
// - "insert", the default: a new part made from the template the request names (NewDocument),
//   and the file inserted into it with IPartDoc.InsertImportedFeature, which goes through 3D
//   Interconnect. SOLIDWORKS never picks a template and never makes an assembly. It needs 3D
//   Interconnect on in the account's import options and is refused when it is off.
// - "load": ISldWorks.LoadFile4(path, "r", data), as File Open imports a file, into a document
//   SOLIDWORKS makes from the account's default part template. The only per-call data used is
//   IImportStepData.MapConfigurationData, which overrides swImportStepConfigData for this import
//   alone, and only when the request gives it.
// - "component": a new assembly made from the template the request names, and the file
//   inserted into it at the origin as one component with IAssemblyDoc.InsertImportedComponent,
//   which also goes through 3D Interconnect. The route for a STEP of several bodies or of an
//   assembly, which the other two cannot take.
//
// What the measuring harness saw in the user's own SOLIDWORKS 2024 SP1 on 2026-10-04: LoadFile4
// of a single-body STEP made a part with one MBimport feature and no dialog. Of fixture o12's
// two-body STEP, with 3D Interconnect on and Assembly Structure Mapping set to "import multiple
// bodies as parts", it made an assembly and stopped behind the New SOLIDWORKS Document template
// dialog for three hours, although "always use default templates" was on. A single-sheet STEP
// of 1,018 faces ran past five minutes behind a modal window while SOLIDWORKS used two cores.
//
// The account's import options are read, never set (they are shared with every session of the
// account), returned with every reply, and the cases they make predictable are refused before
// anything is imported, with details.reason:
// - step_assembly: "insert" or "load" of a STEP with more than one PRODUCT, or with
//   NEXT_ASSEMBLY_USAGE_OCCURRENCE or MAPPED_ITEM: it would become an assembly, which "component"
//   takes. no_bodies: a STEP with no body, whatever the method.
// - interconnect_off: "insert" or "component" while 3D Interconnect is off.
// - several_bodies_insert: "insert" of a STEP that may hold more than one body (counted as for
//   several_bodies_as_assembly, below) while 3D Interconnect makes several bodies parts (the
//   mapping "multiple parts"): SOLIDWORKS faulted (RPC_E_SERVERFAULT) every time it was measured.
// - default_templates_off and default_template_missing: "load" while "always use default
//   templates" is off (SOLIDWORKS asks for a template), or when the default part template it
//   names is not a .prtdot file that exists.
// - several_bodies_as_assembly: "load" of a STEP that may hold more than one body (anything but
//   exactly one body with exactly one shell, as the harness's import gate counted) while the
//   account's options would make several bodies an assembly: 3D Interconnect on and the mapping
//   "multiple parts", or 3D Interconnect off and "import multiple bodies as parts" on. "load" of
//   an IGES file, whose bodies are not counted, is refused only in the first case: the API help
//   says "import multiple bodies as parts" is for STEP and ACIS files only.
// - iges_levels_dialog: "load" of an IGES file while 3D Interconnect is off and "show IGES
//   levels" is on.
// - title_open: "load" of a file whose name is the title of a document open in the instance.
// What remains is listed in the swapi README: chiefly the Import Diagnostics question, which
// depends on faults SOLIDWORKS finds while it imports. The window watch reports any dialog of
// the instance, the reply lists those that appeared while it ran, and a call a dialog blocks is
// ended by its timeout, which ends the instance through its job.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace SolidSeas.SwBridge
{
    // Entity counts of a STEP file, read from its text without SOLIDWORKS: the names followed by an
    // opening parenthesis, outside strings and comments, for the entities that decide whether an
    // import can become an assembly or more than one body.
    sealed class StepCensus
    {
        public static readonly string[] Counted = {
            "PRODUCT", "NEXT_ASSEMBLY_USAGE_OCCURRENCE", "MAPPED_ITEM",
            "MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS", "FACETED_BREP",
            "SHELL_BASED_SURFACE_MODEL", "FACE_BASED_SURFACE_MODEL",
            "TESSELLATED_SOLID", "TESSELLATED_SHELL", "GEOMETRIC_CURVE_SET", "GEOMETRIC_SET",
            "CLOSED_SHELL", "OPEN_SHELL",
        };

        public bool Step;
        public readonly Dictionary<string, int> Entities = new Dictionary<string, int>();

        int this[string name]
        {
            get { int n; return Entities.TryGetValue(name, out n) ? n : 0; }
        }

        public int Products { get { return this["PRODUCT"]; } }
        public int AssemblyLinks { get { return this["NEXT_ASSEMBLY_USAGE_OCCURRENCE"] + this["MAPPED_ITEM"]; } }
        public int Solids { get { return this["MANIFOLD_SOLID_BREP"] + this["BREP_WITH_VOIDS"] + this["FACETED_BREP"]; } }
        public int SurfaceModels { get { return this["SHELL_BASED_SURFACE_MODEL"] + this["FACE_BASED_SURFACE_MODEL"]; } }
        public int Tessellated { get { return this["TESSELLATED_SOLID"] + this["TESSELLATED_SHELL"]; } }
        public int FreeCurves { get { return this["GEOMETRIC_CURVE_SET"] + this["GEOMETRIC_SET"]; } }
        public int Shells { get { return this["CLOSED_SHELL"] + this["OPEN_SHELL"]; } }
        public bool Assembly { get { return Products > 1 || AssemblyLinks > 0; } }
        public bool Bodies { get { return Solids + SurfaceModels + Tessellated > 0; } }

        // Exactly one body, with exactly one shell, and nothing else that may become a body.
        public bool OneBody
        {
            get { return Solids + SurfaceModels == 1 && Tessellated == 0 && FreeCurves == 0 && Shells == 1; }
        }

        public static StepCensus Read(string path)
        {
            StepCensus c = new StepCensus();
            foreach (string name in Counted) c.Entities[name] = 0;
            using (FileStream f = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete, 1 << 16))
            using (BufferedStream s = new BufferedStream(f, 1 << 16))
            {
                c.Step = Header(s);
                if (!c.Step) return c;
                System.Text.StringBuilder word = new System.Text.StringBuilder();
                int b = s.ReadByte();
                while (b >= 0)
                {
                    if (b == '\'')
                    {
                        // A string; '' inside one is a quote and reads as an empty string next to it.
                        do { b = s.ReadByte(); } while (b >= 0 && b != '\'');
                        b = s.ReadByte();
                        continue;
                    }
                    if (b == '/')
                    {
                        b = s.ReadByte();
                        if (b != '*') continue;
                        int last = 0;
                        while ((b = s.ReadByte()) >= 0 && !(last == '*' && b == '/')) last = b;
                        b = s.ReadByte();
                        continue;
                    }
                    if ((b >= 'A' && b <= 'Z') || (b >= 'a' && b <= 'z') || b == '_')
                    {
                        word.Length = 0;
                        while ((b >= 'A' && b <= 'Z') || (b >= 'a' && b <= 'z') || (b >= '0' && b <= '9') || b == '_' || b == '-')
                        {
                            if (word.Length < 64) word.Append((char)b);
                            b = s.ReadByte();
                        }
                        while (b == ' ' || b == '\t' || b == '\r' || b == '\n') b = s.ReadByte();
                        if (b == '(')
                        {
                            string name = word.ToString().ToUpperInvariant();
                            int n;
                            if (c.Entities.TryGetValue(name, out n)) c.Entities[name] = n + 1;
                        }
                        continue;
                    }
                    b = s.ReadByte();
                }
            }
            return c;
        }

        // Whether the file starts, after white space, with "ISO-10303-21;".
        static bool Header(Stream s)
        {
            const string magic = "ISO-10303-21;";
            int b;
            do { b = s.ReadByte(); } while (b == ' ' || b == '\t' || b == '\r' || b == '\n' || b == 0xEF || b == 0xBB || b == 0xBF);
            for (int i = 0; i < magic.Length; i++)
            {
                if (b != magic[i]) return false;
                b = s.ReadByte();
            }
            return true;
        }

        public Dictionary<string, object> Describe()
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["products"] = Products;
            d["assembly_links"] = AssemblyLinks;
            d["solids"] = Solids;
            d["surface_models"] = SurfaceModels;
            d["tessellated"] = Tessellated;
            d["free_curve_sets"] = FreeCurves;
            d["shells"] = Shells;
            d["one_body"] = OneBody;
            Dictionary<string, object> e = new Dictionary<string, object>();
            foreach (KeyValuePair<string, int> kv in Entities) e[kv.Key] = kv.Value;
            d["entities"] = e;
            return d;
        }
    }

    static partial class Operations
    {
        static readonly string[] ImportExtensions = { ".step", ".stp", ".igs", ".iges", ".x_t", ".x_b" };

        // The account's import options this operation reads and reports; it sets none of them.
        static readonly swUserPreferenceToggle_e[] ImportToggles = {
            swUserPreferenceToggle_e.swMultiCAD_Enable3DInterconnect,
            swUserPreferenceToggle_e.swMultiCAD_3DInterconnectMaintainLinks,
            swUserPreferenceToggle_e.swAlwaysUseDefaultTemplates,
            swUserPreferenceToggle_e.swImportAutoRunImportDiagnostics,
            swUserPreferenceToggle_e.swImportAutoRunImportDiagnosticsPersist,
            swUserPreferenceToggle_e.swImportNeutralRunDiagnostics,
            swUserPreferenceToggle_e.swImportNeutral_SolidandSurface,
            swUserPreferenceToggle_e.swImportNeutral_FreeCurvesAndPoints,
            swUserPreferenceToggle_e.swImportNeutralReferencePlane,
            swUserPreferenceToggle_e.swImportNeutral_AttributesAndProperties,
            swUserPreferenceToggle_e.swImportSolidSurface,
            swUserPreferenceToggle_e.swImportFreeCurves,
            swUserPreferenceToggle_e.swImportMultBodyAsPartData,
            swUserPreferenceToggle_e.swImportStepConfigData,
            swUserPreferenceToggle_e.swIGESImportShowLevel,
            swUserPreferenceToggle_e.swImportSolidBody,
            swUserPreferenceToggle_e.swImportSurfaceBody,
            swUserPreferenceToggle_e.swImportIgnoreHiddenEntities,
        };

        static readonly swUserPreferenceIntegerValue_e[] ImportIntegers = {
            swUserPreferenceIntegerValue_e.swImportNeutralAssemblyStructureMapping,
            swUserPreferenceIntegerValue_e.swImportCheckAndRepair,
            swUserPreferenceIntegerValue_e.swImportNeutral_KnitOption,
            swUserPreferenceIntegerValue_e.swImportNeutralUnits,
            swUserPreferenceIntegerValue_e.swImportUnitPreference,
            swUserPreferenceIntegerValue_e.swImportUseBrep,
        };

        static Dictionary<string, object> ImportFile(Args args)
        {
            args.Allow("path", "method", "template", "map_configuration_data", "allow_network");
            string path = args.FullPath("path", args.Bool("allow_network", false));
            string ext = Path.GetExtension(path).ToLowerInvariant();
            if (Array.IndexOf(ImportExtensions, ext) < 0)
                throw new BridgeException("invalid_argument", "imported are " + string.Join(" ", ImportExtensions) + " files");
            string format = ext == ".step" || ext == ".stp" ? "step" : ext == ".igs" || ext == ".iges" ? "iges" : "parasolid";
            string method = args.String("method", "insert");
            if (method != "insert" && method != "load" && method != "component")
                throw new BridgeException("invalid_argument", "method is insert, load or component");
            string template = null;
            if (method == "insert")
            {
                template = args.FullPath("template");
                if (Path.GetExtension(template).ToLowerInvariant() != ".prtdot")
                    throw new BridgeException("invalid_argument", "template must be a part template (.prtdot)");
            }
            else if (method == "component")
            {
                template = args.FullPath("template");
                if (Path.GetExtension(template).ToLowerInvariant() != ".asmdot")
                    throw new BridgeException("invalid_argument", "template must be an assembly template (.asmdot)");
            }
            else if (args.String("template", null) != null)
            {
                throw new BridgeException("invalid_argument", "load makes the document from the default part template the account's options name; give no template");
            }
            bool? mapConfiguration = null;
            if (args.Has("map_configuration_data")) mapConfiguration = args.Bool("map_configuration_data", false);
            if (mapConfiguration.HasValue && (method != "load" || format != "step"))
                throw new BridgeException("invalid_argument", "map_configuration_data is per-call data of a STEP import with load");
            if (template != null && !File.Exists(template)) throw new BridgeException("not_found", "template not found: " + template);
            if (!File.Exists(path)) throw new BridgeException("not_found", "no such file: " + path);
            Dictionary<string, object> facts = new Dictionary<string, object>();
            facts["method"] = method;
            facts["format"] = format;
            // What the file holds decides some cases before SOLIDWORKS is asked anything.
            StepCensus census = null;
            if (format == "step")
            {
                census = StepCensus.Read(path);
                if (!census.Step) throw new BridgeException("invalid_argument", "not a STEP file (no ISO-10303-21 header): " + path);
                facts["step_census"] = census.Describe();
                if (census.Assembly && method != "component")
                    Refuse("step_assembly", "the STEP file holds an assembly (" + census.Products + " products, " + census.AssemblyLinks +
                        " assembly links); SOLIDWORKS would make an assembly of it: use method component", facts);
                if (!census.Bodies) Refuse("no_bodies", "the STEP file holds no solid, surface or tessellated body", facts);
            }

            ISldWorks app = Require();
            Dictionary<string, object> preferences = ImportPreferences(app);
            Dictionary<string, object> templates = DefaultPartTemplate(app);
            facts["preferences"] = preferences;
            facts["default_part_template"] = templates;
            Refusals(method, format, census, preferences, templates, facts);
            if (method == "load") RefuseOpenTitle(app, path, facts);

            int seen = watch != null ? watch.DialogsSeen : 0;
            Stopwatch t = Stopwatch.StartNew();
            int errors = 0;
            int handle = 0;
            Feature feature = null;
            Component2 component = null;
            double[] placed = null;
            try
            {
                if (method == "insert")
                {
                    ModelDoc2 created = NewDocumentHidden(app, template);
                    if (created == null) throw new BridgeException("new_failed", "NewDocument returned no document for " + template);
                    handle = Remember(created);
                    PartDoc part = created as PartDoc;
                    if (part == null) throw new BridgeException("invalid_argument", "the template made no part: " + template);
                    feature = part.InsertImportedFeature(path, out errors) as Feature;
                    KeepHidden(app);
                    if (feature == null)
                        throw new BridgeException("import_failed", "InsertImportedFeature imported nothing from " + path,
                            Failed(facts, errors, seen, t));
                }
                else if (method == "component")
                {
                    ModelDoc2 created = NewDocumentHidden(app, template);
                    if (created == null) throw new BridgeException("new_failed", "NewDocument returned no document for " + template);
                    handle = Remember(created);
                    AssemblyDoc asm = created as AssemblyDoc;
                    if (asm == null) throw new BridgeException("invalid_argument", "the template made no assembly: " + template);
                    object inserted;
                    int status;
                    try
                    {
                        status = asm.InsertImportedComponent(path, 0, 0, 0, out inserted);
                    }
                    finally
                    {
                        KeepHiddenSettled(app);
                    }
                    component = inserted as Component2;
                    if (status != 0 || component == null)
                    {
                        Dictionary<string, object> failed = Failed(facts, 0, seen, t);
                        failed["interconnect_error"] = Enum.GetName(typeof(sw3DInterconnectImportErrors_e), status) ?? status.ToString();
                        throw new BridgeException("import_failed", "InsertImportedComponent imported nothing from " + path +
                            " (" + failed["interconnect_error"] + ")", failed);
                    }
                    // SOLIDWORKS places the component where it likes, whatever the point given
                    // (measured: 6 to 33 mm from the origin, differently each time); it is
                    // moved to the origin, so the file's coordinates are the assembly's.
                    placed = TransformNumbers(component.Transform2);
                    MathUtility math = (MathUtility)app.GetMathUtility();
                    component.Transform2 = (MathTransform)math.CreateTransform(Identity());
                }
                else
                {
                    object data = null;
                    if (mapConfiguration.HasValue)
                    {
                        ImportStepData step = app.GetImportFileData(path) as ImportStepData;
                        if (step == null) throw new BridgeException("import_failed", "SOLIDWORKS gave no STEP import data for " + path, Failed(facts, 0, seen, t));
                        step.MapConfigurationData = mapConfiguration.Value;
                        data = step;
                    }
                    List<string> before = OpenTitles(app);
                    ModelDoc2 loaded = app.LoadFile4(path, "r", data, ref errors);
                    KeepHidden(app);
                    if (loaded == null)
                        throw new BridgeException("import_failed", "LoadFile4 imported nothing from " + path, Failed(facts, errors, seen, t));
                    string title = loaded.GetTitle();
                    if (before.Contains(title))
                    {
                        // Not a new document: it was open before this call, so it is not the bridge's.
                        facts["reason"] = "title_open";
                        throw new BridgeException("refused", "LoadFile4 returned " + title + ", which was open already; it is not touched", facts);
                    }
                    handle = Remember(loaded);
                }
                // Read before answering; a failure here closes the document again too.
                ModelDoc2 doc = documents[handle];
                Dictionary<string, object> d = Describe(handle);
                foreach (KeyValuePair<string, object> kv in facts) d[kv.Key] = kv.Value;
                d["source"] = path;
                d["errors"] = errors;
                if (errors != 0) d["error_names"] = FlagNames(typeof(swFileLoadError_e), errors);
                if (feature != null)
                {
                    Dictionary<string, object> f = new Dictionary<string, object>();
                    f["name"] = feature.Name;
                    f["type"] = feature.GetTypeName2();
                    f["interconnect"] = feature.Is3DInterconnectFeature;
                    d["feature"] = f;
                }
                if (component != null)
                {
                    Dictionary<string, object> c = DescribeComponent(component, path);
                    c["placed"] = placed;
                    double[] now = TransformNumbers(component.Transform2);
                    c["at_origin"] = IsIdentity(now);
                    d["component"] = c;
                }
                d["feature_types"] = FeatureTypes(doc);
                int solids, sheets;
                CountBodies(doc, out solids, out sheets);
                d["solid_bodies"] = solids;
                d["sheet_bodies"] = sheets;
                d["result_kind"] = solids > 0 ? (sheets > 0 ? "solids_and_surfaces" : "solids") : (sheets > 0 ? "surfaces_only" : "empty");
                List<object> dialogs = watch != null ? watch.DialogsSince(seen, 1000) : new List<object>();
                d["dialogs"] = dialogs;
                d["dialog_appeared"] = dialogs.Count > 0;
                d["window_watch"] = watch != null && watch.Running;
                d["seconds"] = Math.Round(t.Elapsed.TotalSeconds, 3);
                return d;
            }
            catch (Exception)
            {
                if (handle != 0 && documents.ContainsKey(handle))
                {
                    try { Close(handle); }
                    catch (Exception e) { Console.Error.WriteLine("import_file: closing document " + handle + ": " + e.Message); }
                }
                throw;
            }
        }

        // The details of an import that brought nothing: what the request was, the account's
        // options, SOLIDWORKS' error code and the dialogs that appeared.
        static Dictionary<string, object> Failed(Dictionary<string, object> facts, int errors, int seen, Stopwatch t)
        {
            Dictionary<string, object> d = new Dictionary<string, object>(facts);
            d["errors"] = errors;
            d["error_names"] = FlagNames(typeof(swFileLoadError_e), errors);
            List<object> dialogs = watch != null ? watch.DialogsSince(seen, 1000) : new List<object>();
            d["dialogs"] = dialogs;
            d["dialog_appeared"] = dialogs.Count > 0;
            d["seconds"] = Math.Round(t.Elapsed.TotalSeconds, 3);
            return d;
        }

        // The component InsertImportedComponent made: its name, how many components it holds (a
        // file of several bodies or of an assembly comes in as a sub-assembly), and whether the
        // document it refers to is the source file; never that document's path, which may be in
        // the account's own folders.
        static Dictionary<string, object> DescribeComponent(Component2 c, string source)
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["name"] = c.Name2;
            string p = c.GetPathName() ?? "";
            d["refers_to_source"] = string.Equals(p, source, StringComparison.OrdinalIgnoreCase);
            d["document_extension"] = Path.GetExtension(p).ToLowerInvariant();
            d["virtual"] = c.IsVirtual;
            object[] children = c.GetChildren() as object[];
            d["children"] = children == null ? 0 : children.Length;
            if (children != null)
            {
                foreach (object o in children)
                    if (o != null && Marshal.IsComObject(o)) Marshal.ReleaseComObject(o);
            }
            return d;
        }

        // A component's transform as SOLIDWORKS gives it: the rotation's nine numbers, then the
        // translation in metres (MathTransform.ArrayData without its scale and padding).
        static double[] TransformNumbers(MathTransform t)
        {
            double[] a = t == null ? null : t.ArrayData as double[];
            if (a == null || a.Length < 12) return null;
            double[] n = new double[12];
            Array.Copy(a, n, 12);
            return n;
        }

        static double[] Identity()
        {
            return new double[] { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 };
        }

        static bool IsIdentity(double[] n)
        {
            if (n == null) return false;
            double[] id = Identity();
            for (int i = 0; i < 12; i++)
            {
                if (Math.Abs(n[i] - id[i]) > 1e-12) return false;
            }
            return true;
        }

        // The cases the account's options make predictable, refused before anything is imported.
        static void Refusals(string method, string format, StepCensus census, Dictionary<string, object> preferences,
            Dictionary<string, object> templates, Dictionary<string, object> facts)
        {
            bool interconnect = (bool)preferences["swMultiCAD_Enable3DInterconnect"];
            int mapping = (int)preferences["swImportNeutralAssemblyStructureMapping"];
            if (method == "insert" || method == "component")
            {
                if (!interconnect)
                    Refuse("interconnect_off", method + " goes through 3D Interconnect, which the account's import options turn off; " +
                        "SolidSeas never turns it on (use method load)", facts);
                // Measured with the mapping "multiple parts": the insert of o12's two solids faulted on
                // 2026-10-05 and 2026-10-14, and of 21 corpus parts of several bodies on 2026-10-05.
                if (method == "insert" && format == "step" && !census.OneBody &&
                    mapping == (int)swImportNeutralAssemblyStructureMapping_e.swImportNeutralAssemblyStructureMapping_MultipleParts)
                    Refuse("several_bodies_insert", "the STEP file may hold more than one body, and while the account's import " +
                        "options make several bodies parts, inserting them into a part faults inside SOLIDWORKS " +
                        "(RPC_E_SERVERFAULT, measured); use method component", facts);
                return;
            }
            if (!(bool)preferences["swAlwaysUseDefaultTemplates"])
                Refuse("default_templates_off", "the account's options do not always use the default templates, so SOLIDWORKS " +
                    "would ask for one; use method insert, which takes a template", facts);
            if (!(bool)templates["exists"] || !(bool)templates["extension_ok"])
                Refuse("default_template_missing", "the default part template the account's options name is not a .prtdot file " +
                    "that exists; use method insert, which takes a template", facts);
            bool asParts = interconnect
                ? mapping == (int)swImportNeutralAssemblyStructureMapping_e.swImportNeutralAssemblyStructureMapping_MultipleParts
                : (bool)preferences["swImportMultBodyAsPartData"];
            if (asParts && format == "step" && !census.OneBody)
                Refuse("several_bodies_as_assembly", "the STEP file may hold more than one body, and the account's import options " +
                    "make several bodies an assembly, for which SOLIDWORKS asked for a template (measured); use method component", facts);
            if (asParts && format == "iges" && interconnect)
                Refuse("several_bodies_as_assembly", "an IGES file's bodies are not counted, and the account's import options make " +
                    "several bodies an assembly, for which SOLIDWORKS asks for a template; use method insert", facts);
            if (format == "iges" && !interconnect && (bool)preferences["swIGESImportShowLevel"])
                Refuse("iges_levels_dialog", "the account's import options show the IGES levels dialog", facts);
        }

        static void Refuse(string reason, string message, Dictionary<string, object> facts)
        {
            facts["reason"] = reason;
            throw new BridgeException("refused", message, facts);
        }

        // LoadFile4 names the new document after the file: a document open under that title would
        // be returned instead of a new one.
        static void RefuseOpenTitle(ISldWorks app, string path, Dictionary<string, object> facts)
        {
            string stem = Path.GetFileNameWithoutExtension(path);
            foreach (string title in OpenTitles(app))
            {
                if (string.Equals(title, stem, StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(Path.GetFileNameWithoutExtension(title), stem, StringComparison.OrdinalIgnoreCase))
                    Refuse("title_open", "a document titled " + title + " is open in the instance; LoadFile4 would give it back", facts);
            }
        }

        static List<string> OpenTitles(ISldWorks app)
        {
            List<string> titles = new List<string>();
            object[] open = app.GetDocuments() as object[];
            if (open == null) return titles;
            foreach (object o in open)
            {
                ModelDoc2 doc = o as ModelDoc2;
                if (doc != null) titles.Add(doc.GetTitle());
                if (o != null && Marshal.IsComObject(o) && !IsRemembered(o)) Marshal.ReleaseComObject(o);
            }
            return titles;
        }

        // Read, never set: SOLIDWORKS user preferences, shared with every session of this account.
        static Dictionary<string, object> ImportPreferences(ISldWorks app)
        {
            Dictionary<string, object> p = new Dictionary<string, object>();
            foreach (swUserPreferenceToggle_e toggle in ImportToggles)
                p[toggle.ToString()] = app.GetUserPreferenceToggle((int)toggle);
            foreach (swUserPreferenceIntegerValue_e value in ImportIntegers)
                p[value.ToString()] = app.GetUserPreferenceIntegerValue((int)value);
            return p;
        }

        // Whether the default part template the account's options name exists and is a part
        // template; never its path, which may name the user's own folders.
        static Dictionary<string, object> DefaultPartTemplate(ISldWorks app)
        {
            string s = app.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart);
            Dictionary<string, object> d = new Dictionary<string, object>();
            bool named = !string.IsNullOrEmpty(s) && s.IndexOfAny(Path.GetInvalidPathChars()) < 0;
            d["exists"] = named && File.Exists(s);
            d["extension_ok"] = named && string.Equals(Path.GetExtension(s), ".prtdot", StringComparison.OrdinalIgnoreCase);
            return d;
        }

        // How many features of each type the document has, in the order of their type names.
        static Dictionary<string, object> FeatureTypes(ModelDoc2 doc)
        {
            SortedDictionary<string, int> counts = new SortedDictionary<string, int>(StringComparer.Ordinal);
            Feature f = doc.FirstFeature() as Feature;
            for (int guard = 0; f != null && guard < 100000; guard++)
            {
                string type = f.GetTypeName2() ?? "";
                int n;
                counts.TryGetValue(type, out n);
                counts[type] = n + 1;
                Feature next = f.GetNextFeature() as Feature;
                Marshal.ReleaseComObject(f);
                f = next;
            }
            if (f != null) Marshal.ReleaseComObject(f);
            Dictionary<string, object> d = new Dictionary<string, object>();
            foreach (KeyValuePair<string, int> kv in counts) d[kv.Key] = kv.Value;
            return d;
        }

        // Solid and sheet bodies, hidden ones included: of a part, or of an assembly's components.
        static void CountBodies(ModelDoc2 doc, out int solids, out int sheets)
        {
            solids = sheets = 0;
            PartDoc part = doc as PartDoc;
            if (part != null)
            {
                solids = Count(part.GetBodies2((int)swBodyType_e.swSolidBody, false) as object[]);
                sheets = Count(part.GetBodies2((int)swBodyType_e.swSheetBody, false) as object[]);
                return;
            }
            AssemblyDoc asm = doc as AssemblyDoc;
            if (asm == null) return;
            List<BodyRef> bodies = new List<BodyRef>();
            Components(doc, asm, bodies);
            foreach (BodyRef b in bodies)
            {
                if (b.Sheet) sheets++;
                else solids++;
            }
        }
    }
}
