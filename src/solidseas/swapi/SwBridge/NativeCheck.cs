// native_check: what SOLIDWORKS makes of a part the native writer produced.
//
// The standalone writer (docs/NATIVE_SLDPRT_WRITER.md) makes .sldprt files with no SOLIDWORKS
// running. This operation is its oracle, run only in the instance the bridge started for batch
// work, on a document open_document opened read-only. It reports the feature tree as opened
// (each feature's type, suppression, error code, dimensions, a sketch's segments, points,
// relations and constrained state, an extrusion's end condition and depth), the What's Wrong
// list and the measures; then forces a full rebuild and reports them again; then, when asked,
// sets one dimension, rebuilds and reports again; and last, when asked, saves a native copy
// with swSaveAsOptions_Copy to a new .sldprt path (never over a file, never over the document's
// own). The document itself is never saved, and nothing is selected.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace SolidSeas.SwBridge
{
    static partial class Operations
    {
        const int NativeCheckMaxFeatures = 2000;
        const int NativeCheckMaxDimensions = 500;

        public static void RegisterNativeCheck(Dictionary<string, Handler> handlers)
        {
            handlers["native_check"] = NativeCheck;
        }

        static Dictionary<string, object> NativeCheck(Args args)
        {
            args.Allow("doc", "dimension", "value", "save_path");
            int handle;
            ModelDoc2 doc = Document(args, out handle);
            Dictionary<string, object> d = NativeCheckOn(doc, args);
            d["doc"] = handle;
            return d;
        }

        // The check itself, on a document this bridge opened or created (batch or test session).
        static Dictionary<string, object> NativeCheckOn(ModelDoc2 doc, Args args)
        {
            if (doc.GetType() != (int)swDocumentTypes_e.swDocPART)
                throw new BridgeException("invalid_argument", "native_check takes a part");
            string dimension = args.String("dimension", "");
            string savePath = args.String("save_path", "");
            string target = savePath.Length > 0 ? args.FullPath("save_path", false) : null;
            if (target != null)
            {
                if (!string.Equals(Path.GetExtension(target), ".sldprt", StringComparison.OrdinalIgnoreCase))
                    throw new BridgeException("invalid_argument", "save_path names a .sldprt file");
                string own = doc.GetPathName();
                if (!string.IsNullOrEmpty(own) && string.Equals(Path.GetFullPath(own), target, StringComparison.OrdinalIgnoreCase))
                    throw new BridgeException("refused", "a document is never saved over its own file");
                string folder = Path.GetDirectoryName(target);
                if (folder == null || !Directory.Exists(folder)) throw new BridgeException("not_found", "no such folder: " + folder);
                if (File.Exists(target) || Directory.Exists(target))
                    throw new BridgeException("refused", "save_path exists; a native copy never replaces a file");
            }

            Dictionary<string, object> d = new Dictionary<string, object>();
            d["opened"] = NativeSnapshot(doc);
            d["force_rebuild"] = doc.ForceRebuild3(false);
            d["rebuilt"] = NativeSnapshot(doc);

            if (dimension.Length > 0)
            {
                Dictionary<string, object> edit = new Dictionary<string, object>();
                edit["dimension"] = dimension;
                Dimension dim = doc.Parameter(dimension) as Dimension;
                edit["found"] = dim != null;
                if (dim != null)
                {
                    double value = args.Number("value");
                    edit["before"] = DimensionValue(dim);
                    edit["status"] = dim.SetSystemValue3(value, (int)swSetValueInConfiguration_e.swSetValue_InThisConfiguration, null);
                    edit["rebuild"] = doc.EditRebuild3();
                    edit["after"] = DimensionValue(dim);
                    edit["snapshot"] = NativeSnapshot(doc);
                    Marshal.ReleaseComObject(dim);
                }
                d["edit"] = edit;
            }

            if (target != null)
            {
                int errors = 0, warnings = 0;
                int options = (int)swSaveAsOptions_e.swSaveAsOptions_Silent | (int)swSaveAsOptions_e.swSaveAsOptions_Copy;
                bool ok = doc.Extension.SaveAs3(target, (int)swSaveAsVersion_e.swSaveAsCurrentVersion, options, null, null,
                                                ref errors, ref warnings);
                Dictionary<string, object> saved = new Dictionary<string, object>();
                saved["ok"] = ok;
                saved["path"] = target;
                saved["bytes"] = File.Exists(target) ? new FileInfo(target).Length : 0;
                saved["errors"] = errors;
                saved["warnings"] = warnings;
                if (errors != 0) saved["error_names"] = FlagNames(typeof(swFileSaveError_e), errors);
                d["saved"] = saved;
            }
            d["dirty"] = doc.GetSaveFlag();
            return d;
        }

        static Dictionary<string, object> NativeSnapshot(ModelDoc2 doc)
        {
            Dictionary<string, object> s = new Dictionary<string, object>();
            List<object> features = new List<object>();
            Feature feature = doc.FirstFeature() as Feature;
            while (feature != null && features.Count < NativeCheckMaxFeatures)
            {
                features.Add(NativeFeature(feature));
                Feature next = feature.GetNextFeature() as Feature;
                Marshal.ReleaseComObject(feature);
                feature = next;
            }
            s["truncated"] = feature != null;
            if (feature != null) Marshal.ReleaseComObject(feature);
            s["features"] = features;
            s["whats_wrong"] = NativeWhatsWrong(doc);
            s["measure"] = Measure(doc);
            return s;
        }

        static Dictionary<string, object> NativeFeature(Feature feature)
        {
            Dictionary<string, object> f = new Dictionary<string, object>();
            string type = feature.GetTypeName2();
            f["name"] = feature.Name;
            f["type"] = type;
            f["suppressed"] = feature.IsSuppressed();
            bool isWarning;
            f["error"] = feature.GetErrorCode2(out isWarning);
            f["error_is_warning"] = isWarning;

            List<object> dims = new List<object>();
            DisplayDimension display = feature.GetFirstDisplayDimension() as DisplayDimension;
            while (display != null && dims.Count < NativeCheckMaxDimensions)
            {
                Dimension dim = display.GetDimension2(0) as Dimension;
                if (dim != null)
                {
                    Dictionary<string, object> x = new Dictionary<string, object>();
                    x["name"] = dim.FullName;
                    x["value"] = DimensionValue(dim);
                    x["driven"] = dim.DrivenState;
                    dims.Add(x);
                    Marshal.ReleaseComObject(dim);
                }
                DisplayDimension next = feature.GetNextDisplayDimension(display) as DisplayDimension;
                Marshal.ReleaseComObject(display);
                display = next;
            }
            if (display != null) Marshal.ReleaseComObject(display);
            if (dims.Count > 0) f["dimensions"] = dims;

            if (type == "ProfileFeature" || type == "3DProfileFeature")
            {
                Sketch sketch = feature.GetSpecificFeature2() as Sketch;
                if (sketch != null) f["sketch"] = NativeSketch(sketch);
            }
            else if (type == "Extrusion" || type == "Cut" || type == "BaseBody")
            {
                ExtrudeFeatureData2 ex = feature.GetDefinition() as ExtrudeFeatureData2;
                if (ex != null)
                {
                    Dictionary<string, object> e = new Dictionary<string, object>();
                    e["end_condition"] = ex.GetEndCondition(true);
                    e["depth"] = Finite(ex.GetDepth(true));
                    e["both_directions"] = ex.BothDirections;
                    e["reverse"] = ex.ReverseDirection;
                    e["merge"] = ex.Merge;
                    f["extrude"] = e;
                    Marshal.ReleaseComObject(ex);
                }
            }
            return f;
        }

        static Dictionary<string, object> NativeSketch(Sketch sketch)
        {
            Dictionary<string, object> k = new Dictionary<string, object>();
            List<object> segments = new List<object>();
            object[] segs = sketch.GetSketchSegments() as object[];
            if (segs != null)
            {
                foreach (object o in segs)
                {
                    SketchSegment seg = o as SketchSegment;
                    if (seg == null) continue;
                    Dictionary<string, object> g = new Dictionary<string, object>();
                    g["type"] = seg.GetType();
                    g["construction"] = seg.ConstructionGeometry;
                    g["length"] = Finite(seg.GetLength());
                    segments.Add(g);
                }
            }
            k["segments"] = segments;
            object[] points = sketch.GetSketchPoints2() as object[];
            k["points"] = points == null ? 0 : points.Length;
            List<object> relations = new List<object>();
            SketchRelationManager manager = sketch.RelationManager;
            if (manager != null)
            {
                object[] rels = manager.GetRelations((int)swSketchRelationFilterType_e.swAll) as object[];
                if (rels != null)
                {
                    foreach (object o in rels)
                    {
                        SketchRelation rel = o as SketchRelation;
                        if (rel != null) relations.Add(rel.GetRelationType());
                    }
                }
            }
            k["relations"] = relations;
            k["constrained_status"] = sketch.GetConstrainedStatus();
            return k;
        }

        static List<object> NativeWhatsWrong(ModelDoc2 doc)
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
                Feature f = fs[i] as Feature;
                e["feature"] = f != null ? f.Name : null;
                e["code"] = cs[i];
                e["warning"] = ws[i];
                list.Add(e);
            }
            return list;
        }
    }
}
