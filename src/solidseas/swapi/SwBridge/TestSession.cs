// Test-session operations: how the opt-in tests and the attached SOLIDWORKS checks work in a
// SOLIDWORKS the person started, offered only when the bridge runs with --test-session.
//
// The person agreed on 2026-10-19, while their licence for SolidSeas' own instance was
// deactivated, that the opt-in tests may use their open session to: create parts from a
// template, open the native writer's candidate parts read-only, model in, rebuild and change
// a dimension of those documents, save copies of them to new files, and close them. Everything
// else stays refused. Only documents this bridge created or opened in the session are touched;
// opening a file the session already has open is refused, because it may be the person's; the
// documents are closed with QuitDoc, which discards their changes, and every one still open
// when the bridge detaches is closed then; nothing is imported, no option is changed, and the
// session is never ended. The bridge reaches the session only through live_attach, that is the
// SolidWorks_PID_<pid> moniker.
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
        // Documents this bridge created or opened in the attached session, by key: the only
        // ones the test-session operations touch.
        static readonly Dictionary<string, ModelDoc2> testDocuments = new Dictionary<string, ModelDoc2>(StringComparer.OrdinalIgnoreCase);

        public static void RegisterTestSession(Dictionary<string, Handler> handlers)
        {
            handlers["test_session_new_part"] = TestSessionNewPart;
            handlers["test_session_open"] = TestSessionOpen;
            handlers["test_session_native_check"] = TestSessionNativeCheck;
            handlers["test_session_close"] = TestSessionClose;
            handlers["test_session_documents"] = TestSessionDocuments;
        }

        static ISldWorks TestSessionApp()
        {
            if (live == null) throw new BridgeException("not_attached", "live_attach to the session first");
            return live;
        }

        static ModelDoc2 TestDocument(Args args, out string key)
        {
            key = args.String("document", "");
            ModelDoc2 doc;
            if (!testDocuments.TryGetValue(key, out doc))
                throw new BridgeException("refused", "not a document this bridge created or opened in the session");
            return doc;
        }

        static Dictionary<string, object> TestSessionNewPart(Args args)
        {
            args.Allow("template");
            ISldWorks app = TestSessionApp();
            string template = args.FullPath("template", false);
            if (!string.Equals(Path.GetExtension(template), ".prtdot", StringComparison.OrdinalIgnoreCase) || !File.Exists(template))
                throw new BridgeException("invalid_argument", "template names a .prtdot file that exists");
            ModelDoc2 doc = app.NewDocument(template, 0, 0, 0) as ModelDoc2;
            if (doc == null) throw new BridgeException("failed", "NewDocument made no part");
            string key = doc.GetTitle();
            testDocuments[key] = doc;
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["title"] = key;
            return d;
        }

        static Dictionary<string, object> TestSessionOpen(Args args)
        {
            args.Allow("path");
            ISldWorks app = TestSessionApp();
            string path = args.FullPath("path", false);
            if (!string.Equals(Path.GetExtension(path), ".sldprt", StringComparison.OrdinalIgnoreCase))
                throw new BridgeException("invalid_argument", "only .sldprt parts are opened");
            if (!File.Exists(path)) throw new BridgeException("not_found", "no such file: " + path);
            if (app.GetOpenDocumentByName(path) != null || app.GetOpenDocumentByName(Path.GetFileName(path)) != null)
                throw new BridgeException("refused", "the session has a document of that name open; it may be the person's");
            int errors = 0, warnings = 0;
            int options = (int)swOpenDocOptions_e.swOpenDocOptions_Silent | (int)swOpenDocOptions_e.swOpenDocOptions_ReadOnly;
            ModelDoc2 doc = app.OpenDoc6(path, (int)swDocumentTypes_e.swDocPART, options, "", ref errors, ref warnings) as ModelDoc2;
            if (doc == null)
            {
                Dictionary<string, object> details = new Dictionary<string, object>();
                details["errors"] = errors;
                details["warnings"] = warnings;
                details["error_names"] = FlagNames(typeof(swFileLoadError_e), errors);
                details["warning_names"] = FlagNames(typeof(swFileLoadWarning_e), warnings);
                throw new BridgeException("open_failed", "OpenDoc6 failed for " + path, details);
            }
            string key = doc.GetPathName();
            if (string.IsNullOrEmpty(key)) key = doc.GetTitle();
            testDocuments[key] = doc;
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["title"] = doc.GetTitle();
            d["errors"] = errors;
            d["warnings"] = warnings;
            if (warnings != 0) d["warning_names"] = FlagNames(typeof(swFileLoadWarning_e), warnings);
            return d;
        }

        static Dictionary<string, object> TestSessionNativeCheck(Args args)
        {
            args.Allow("document", "dimension", "value", "save_path");
            TestSessionApp();
            string key;
            ModelDoc2 doc = TestDocument(args, out key);
            Dictionary<string, object> d = NativeCheckOn(doc, args);
            d["document"] = key;
            return d;
        }

        static Dictionary<string, object> TestSessionClose(Args args)
        {
            args.Allow("document");
            ISldWorks app = TestSessionApp();
            string key;
            ModelDoc2 doc = TestDocument(args, out key);
            string title = doc.GetTitle();
            app.QuitDoc(title);
            testDocuments.Remove(key);
            try { Marshal.ReleaseComObject(doc); }
            catch (Exception) { }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["document"] = key;
            d["title"] = title;
            d["closed"] = true;
            return d;
        }

        static Dictionary<string, object> TestSessionDocuments(Args args)
        {
            args.Allow();
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["documents"] = new List<object>(testDocuments.Keys);
            return d;
        }

        // Every document this bridge created or opened in the session, closed without saving.
        static void CloseTestDocuments()
        {
            if (live == null || testDocuments.Count == 0) return;
            foreach (KeyValuePair<string, ModelDoc2> kv in new List<KeyValuePair<string, ModelDoc2>>(testDocuments))
            {
                try { live.QuitDoc(kv.Value.GetTitle()); }
                catch (Exception e) { Console.Error.WriteLine("closing " + kv.Key + ": " + e.Message); }
                try { Marshal.ReleaseComObject(kv.Value); }
                catch (Exception) { }
            }
            testDocuments.Clear();
        }
    }
}
