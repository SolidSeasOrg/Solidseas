// SolidSeas.SwBridge: the only SolidSeas code that calls SOLIDWORKS.
//
// Python starts it as a child process (solidseas.swapi.bridge). Its main thread is
// a single-threaded apartment that owns every SOLIDWORKS object, registers a COM
// message filter so calls that SOLIDWORKS rejects while busy are retried, and
// dispatches window messages whenever it waits. SOLIDWORKS document notifications do
// not depend on that: they arrive on a COM worker thread whatever the main thread is
// doing, even blocked (measured; docs/ARCHITECTURE.md section 6), and SOLIDWORKS waits
// for each handler, so a handler only queues its event line and returns. It reads one
// JSON request per line on standard input and writes one JSON reply per line on
// standard output, through a writer thread that never makes a handler wait, and it runs
// only its own named operations (Operations.cs), never code. Standard error carries
// diagnostics only.
//
// The caller keeps the timeouts: a call stuck inside SOLIDWORKS blocks this thread,
// so solidseas.swapi.bridge ends this process, and the SOLIDWORKS it started, through
// the Job Object it put this process in.
//
// Written in C# 5 for the .NET Framework compiler that ships with Windows (csc.exe in
// Microsoft.NET\Framework64\v4.0.30319). scripts/build-bridge.ps1, or
// "python -m solidseas.swapi build", compiles it against the SOLIDWORKS interop
// assemblies in <SOLIDWORKS>\api\redist, which are never copied: the bridge loads
// them from the folder given with --interop when it first needs them.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace SolidSeas.SwBridge
{
    // A refusal or failure the caller can act on: Code is one of the protocol's error codes.
    sealed class BridgeException : Exception
    {
        public readonly string Code;
        public readonly Dictionary<string, object> Details;

        public BridgeException(string code, string message) : this(code, message, null) { }

        public BridgeException(string code, string message, Dictionary<string, object> details) : base(message)
        {
            Code = code;
            Details = details;
        }
    }

    static class Program
    {
        public const int Protocol = 1;
        public const string DefaultSolidWorksFolder = @"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS";
        public static string InteropFolder = Path.Combine(DefaultSolidWorksFolder, @"api\redist");
        public static bool TestOps;
        public static bool TestSession;

        [STAThread]
        static int Main(string[] args)
        {
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--interop" && i + 1 < args.Length) InteropFolder = args[++i];
                else if (args[i] == "--test-ops") TestOps = true;
                else if (args[i] == "--test-session") TestSession = true;
                else
                {
                    Console.Error.WriteLine("usage: SolidSeas.SwBridge.exe [--interop FOLDER] [--test-ops] [--test-session]");
                    return 2;
                }
            }
            // The interop assemblies are resolved from the SOLIDWORKS installation, and the
            // handler must be in place before any method that uses their types is compiled.
            AppDomain.CurrentDomain.AssemblyResolve += ResolveInterop;
            return Bridge.Run();
        }

        static Assembly ResolveInterop(object sender, ResolveEventArgs e)
        {
            string name = new AssemblyName(e.Name).Name;
            if (!name.StartsWith("SolidWorks.Interop.", StringComparison.OrdinalIgnoreCase)) return null;
            string path = Path.Combine(InteropFolder, name + ".dll");
            return File.Exists(path) ? Assembly.LoadFrom(path) : null;
        }
    }

    // Outgoing call deadlines for the request being handled.
    static class Request
    {
        static int deadline;

        public static void Begin(double timeoutSeconds)
        {
            // Leave the caller a margin, so the bridge's own waits end before the caller gives up.
            double ms = Math.Max(0, timeoutSeconds * 1000.0 - 2000.0);
            deadline = unchecked(Environment.TickCount + (int)Math.Min(ms, int.MaxValue / 2));
        }

        public static int RemainingMs()
        {
            return Math.Max(0, unchecked(deadline - Environment.TickCount));
        }
    }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("00000016-0000-0000-C000-000000000046")]
    interface IOleMessageFilter
    {
        [PreserveSig] int HandleInComingCall(int dwCallType, IntPtr hTaskCaller, int dwTickCount, IntPtr lpInterfaceInfo);
        [PreserveSig] int RetryRejectedCall(IntPtr hTaskCallee, int dwTickCount, int dwRejectType);
        [PreserveSig] int MessagePending(IntPtr hTaskCallee, int dwTickCount, int dwPendingType);
    }

    // Retries a call that SOLIDWORKS rejects because it is busy (SERVERCALL_RETRYLATER) until
    // the current request's deadline, then lets it fail with RPC_E_CALL_REJECTED.
    sealed class MessageFilter : IOleMessageFilter
    {
        [DllImport("ole32.dll")]
        static extern int CoRegisterMessageFilter(IOleMessageFilter newFilter, out IOleMessageFilter oldFilter);

        public static bool Register()
        {
            IOleMessageFilter old;
            return CoRegisterMessageFilter(new MessageFilter(), out old) == 0;
        }

        public int HandleInComingCall(int dwCallType, IntPtr hTaskCaller, int dwTickCount, IntPtr lpInterfaceInfo)
        {
            // SERVERCALL_ISHANDLED. This filter sees only calls into this apartment; SOLIDWORKS
            // calls the event handlers on a COM worker thread, which never comes through here.
            return 0;
        }

        public int RetryRejectedCall(IntPtr hTaskCallee, int dwTickCount, int dwRejectType)
        {
            if (dwRejectType == 2 && Request.RemainingMs() > 250) return 250; // retry in 250 ms
            return -1; // cancel: the call fails with RPC_E_CALL_REJECTED
        }

        public int MessagePending(IntPtr hTaskCallee, int dwTickCount, int dwPendingType)
        {
            return 2; // PENDINGMSG_WAITDEFPROCESS
        }
    }

    // Waits that keep the apartment's message queue moving.
    static class Pump
    {
        [StructLayout(LayoutKind.Sequential)]
        struct Msg
        {
            public IntPtr hwnd;
            public uint message;
            public IntPtr wParam, lParam;
            public uint time;
            public int x, y;
        }

        [DllImport("user32.dll", SetLastError = true)]
        static extern uint MsgWaitForMultipleObjectsEx(uint count, IntPtr[] handles, uint milliseconds, uint wakeMask, uint flags);
        [DllImport("user32.dll")]
        static extern bool PeekMessage(out Msg msg, IntPtr hwnd, uint min, uint max, uint remove);
        [DllImport("user32.dll")]
        static extern bool TranslateMessage(ref Msg msg);
        [DllImport("user32.dll")]
        static extern IntPtr DispatchMessage(ref Msg msg);

        const uint QS_ALLINPUT = 0x04FF, MWMO_INPUTAVAILABLE = 0x0004, PM_REMOVE = 1;
        const uint WAIT_TIMEOUT = 258, WAIT_FAILED = 0xFFFFFFFF, INFINITE = 0xFFFFFFFF;

        // Waits until the handle is signalled (true) or the time is up (false), dispatching
        // messages meanwhile. IntPtr.Zero waits for the time alone; a negative time waits forever.
        public static bool Wait(IntPtr handle, int milliseconds)
        {
            IntPtr[] handles = handle == IntPtr.Zero ? new IntPtr[0] : new IntPtr[] { handle };
            uint count = (uint)handles.Length;
            int start = Environment.TickCount;
            while (true)
            {
                uint wait = INFINITE;
                if (milliseconds >= 0) wait = (uint)Math.Max(0, milliseconds - unchecked(Environment.TickCount - start));
                uint r = MsgWaitForMultipleObjectsEx(count, handles, wait, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
                if (count > 0 && r == 0) return true;
                if (r == count)
                {
                    Msg msg;
                    while (PeekMessage(out msg, IntPtr.Zero, 0, 0, PM_REMOVE))
                    {
                        TranslateMessage(ref msg);
                        DispatchMessage(ref msg);
                    }
                    if (milliseconds >= 0 && unchecked(Environment.TickCount - start) >= milliseconds) return false;
                    continue;
                }
                if (r == WAIT_TIMEOUT) return false;
                if (r == WAIT_FAILED)
                    throw new BridgeException("internal", "MsgWaitForMultipleObjectsEx failed: " + Marshal.GetLastWin32Error());
                return false;
            }
        }

        public static void Sleep(int milliseconds)
        {
            Wait(IntPtr.Zero, milliseconds);
        }
    }

    // Reads request lines on a background thread, so the apartment thread can pump while it waits.
    sealed class LineReader
    {
        public const int MaxLine = 1 << 20;

        public sealed class Line
        {
            public string Text;
            public bool TooLong, End;
        }

        readonly Queue<Line> lines = new Queue<Line>();
        readonly AutoResetEvent arrived = new AutoResetEvent(false);

        public void Start(Stream input)
        {
            Thread t = new Thread(delegate() { Loop(input); });
            t.IsBackground = true;
            t.Name = "stdin";
            t.Start();
        }

        void Loop(Stream input)
        {
            try
            {
                StreamReader reader = new StreamReader(input, new UTF8Encoding(false, false), false, 1 << 16);
                StringBuilder text = new StringBuilder();
                bool tooLong = false;
                while (true)
                {
                    int c = reader.Read();
                    if (c < 0) break;
                    if (c == '\n')
                    {
                        Push(new Line { Text = text.ToString().TrimEnd('\r'), TooLong = tooLong });
                        text.Length = 0;
                        tooLong = false;
                    }
                    else if (!tooLong)
                    {
                        if (text.Length >= MaxLine) { tooLong = true; text.Length = 0; }
                        else text.Append((char)c);
                    }
                }
                if (text.Length > 0 || tooLong) Push(new Line { Text = text.ToString(), TooLong = tooLong });
            }
            catch (IOException) { }
            catch (ObjectDisposedException) { }
            Push(new Line { End = true });
        }

        void Push(Line line)
        {
            lock (lines) lines.Enqueue(line);
            arrived.Set();
        }

        // The next line, waiting with the message pump running.
        public Line Next()
        {
            while (true)
            {
                lock (lines)
                {
                    if (lines.Count > 0) return lines.Dequeue();
                }
                Pump.Wait(arrived.SafeWaitHandle.DangerousGetHandle(), -1);
            }
        }
    }

    static class Json
    {
        static readonly JavaScriptSerializer serializer = new JavaScriptSerializer { MaxJsonLength = int.MaxValue, RecursionLimit = 64 };

        public static object Parse(string text)
        {
            return serializer.DeserializeObject(text);
        }

        // Replies come from the apartment thread and events from SOLIDWORKS' worker threads:
        // one at a time through the shared serializer.
        public static string Write(object value)
        {
            lock (serializer) return serializer.Serialize(value);
        }
    }

    // Standard output carries protocol lines only; anything else written to Console goes to standard error.
    //
    // One writer thread writes every line, in the order they were queued. Replies are never
    // dropped. Events come from SOLIDWORKS' notification handlers, and SOLIDWORKS waits for
    // each handler to return, so a handler must never wait for the pipe: an event is queued
    // and never waited for, and once MaxQueuedEvents events wait unwritten (the client is not
    // reading), further ones are counted as lost. The next line queued after a loss is an
    // {"event": "events_lost", "count": n} line, so the client knows it missed something.
    static class Output
    {
        public const int MaxQueuedEvents = 4096;

        sealed class Item
        {
            public string Text;
            public bool IsEvent;
        }

        static StreamWriter writer;
        static readonly object gate = new object();
        static readonly Queue<Item> queue = new Queue<Item>();
        static int queuedEvents;
        static long lost, totalLost;
        static bool broken, writing;

        public static void Open()
        {
            writer = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false));
            writer.NewLine = "\n";
            Console.SetOut(Console.Error);
            Thread t = new Thread(Loop);
            t.IsBackground = true;
            t.Name = "stdout";
            t.Start();
        }

        public static long EventsLost
        {
            get { lock (gate) return totalLost; }
        }

        // A reply, or the ready line. Throws IOException once standard output has failed.
        public static void Send(Dictionary<string, object> message)
        {
            string line = Json.Write(message);
            lock (gate)
            {
                if (broken) throw new IOException("standard output is closed");
                ReportLoss();
                queue.Enqueue(new Item { Text = line });
                Monitor.PulseAll(gate);
            }
        }

        // An event, from any thread. Never waits for the pipe.
        public static void Event(Dictionary<string, object> message)
        {
            string line = Json.Write(message);
            lock (gate)
            {
                if (broken) return;
                if (queuedEvents >= MaxQueuedEvents)
                {
                    lost++;
                    totalLost++;
                    return;
                }
                ReportLoss();
                queue.Enqueue(new Item { Text = line, IsEvent = true });
                queuedEvents++;
                Monitor.PulseAll(gate);
            }
        }

        // Called holding the gate: queues how many events were dropped since the last line.
        static void ReportLoss()
        {
            if (lost == 0) return;
            Dictionary<string, object> e = new Dictionary<string, object>();
            e["event"] = "events_lost";
            e["count"] = lost;
            queue.Enqueue(new Item { Text = Json.Write(e), IsEvent = true });
            queuedEvents++;
            lost = 0;
        }

        // Waits until every queued line is written, standard output fails, or the time is up.
        public static void Drain(int milliseconds)
        {
            int start = Environment.TickCount;
            lock (gate)
            {
                while ((queue.Count > 0 || writing) && !broken)
                {
                    int left = milliseconds - unchecked(Environment.TickCount - start);
                    if (left <= 0) return;
                    Monitor.Wait(gate, left);
                }
            }
        }

        static void Loop()
        {
            while (true)
            {
                Item item;
                lock (gate)
                {
                    while (queue.Count == 0) Monitor.Wait(gate);
                    item = queue.Dequeue();
                    if (item.IsEvent) queuedEvents--;
                    writing = true;
                }
                try
                {
                    writer.Write(item.Text);
                    writer.Write('\n');
                    writer.Flush();
                }
                catch (Exception e)
                {
                    if (!(e is IOException) && !(e is ObjectDisposedException)) Console.Error.WriteLine("standard output: " + e.Message);
                    lock (gate)
                    {
                        broken = true;
                        writing = false;
                        queue.Clear();
                        queuedEvents = 0;
                        Monitor.PulseAll(gate);
                    }
                    return;
                }
                lock (gate)
                {
                    writing = false;
                    Monitor.PulseAll(gate);
                }
            }
        }
    }

    // The arguments of one request, checked as they are read. Unknown keys are refused.
    sealed class Args
    {
        readonly Dictionary<string, object> values;

        public Args(Dictionary<string, object> values)
        {
            this.values = values ?? new Dictionary<string, object>();
        }

        public void Allow(params string[] keys)
        {
            foreach (string key in values.Keys)
            {
                if (Array.IndexOf(keys, key) < 0) throw new BridgeException("invalid_argument", "unknown argument: " + key);
            }
        }

        object Get(string key)
        {
            object value;
            return values.TryGetValue(key, out value) ? value : null;
        }

        // Whether the request gives the key a value (JSON null counts as not given).
        public bool Has(string key)
        {
            return Get(key) != null;
        }

        public string String(string key, string fallback)
        {
            object value = Get(key);
            if (value == null) return fallback;
            string s = value as string;
            if (s == null) throw new BridgeException("invalid_argument", key + " must be a string");
            return s;
        }

        // The same arguments without the keys named.
        public Args Without(params string[] keys)
        {
            Dictionary<string, object> rest = new Dictionary<string, object>(values);
            foreach (string key in keys) rest.Remove(key);
            return new Args(rest);
        }

        // The value as parsed (a string, number, bool, array or object), or null when absent.
        public object Raw(string key)
        {
            return Get(key);
        }

        // A required finite number.
        public double Number(string key)
        {
            object value = Get(key);
            if (value == null) throw new BridgeException("invalid_argument", key + " is required");
            return NumberOf(value, key);
        }

        public static double NumberOf(object value, string what)
        {
            double n;
            if (value is int) n = (int)value;
            else if (value is long) n = (long)value;
            else if (value is decimal) n = (double)(decimal)value;
            else if (value is double) n = (double)value;
            else throw new BridgeException("invalid_argument", what + " must be a number");
            if (double.IsNaN(n) || double.IsInfinity(n)) throw new BridgeException("invalid_argument", what + " must be finite");
            return n;
        }

        public bool Bool(string key, bool fallback)
        {
            object value = Get(key);
            if (value == null) return fallback;
            if (!(value is bool)) throw new BridgeException("invalid_argument", key + " must be true or false");
            return (bool)value;
        }

        // A JSON array, empty when the key is absent.
        public object[] List(string key)
        {
            object value = Get(key);
            if (value == null) return new object[0];
            object[] items = value as object[];
            if (items == null) throw new BridgeException("invalid_argument", key + " must be a JSON array");
            return items;
        }

        // One item of a JSON array that must be an object, read with the same checks.
        public static Args Item(object item, string key)
        {
            Dictionary<string, object> values = item as Dictionary<string, object>;
            if (values == null) throw new BridgeException("invalid_argument", "each item of " + key + " must be a JSON object");
            return new Args(values);
        }

        public static int WholeNumber(object item, string key)
        {
            if (item is int) return (int)item;
            throw new BridgeException("invalid_argument", "each item of " + key + " must be a whole number");
        }

        public int Int(string key, int fallback, int min, int max)
        {
            object value = Get(key);
            if (value == null) return fallback;
            long n;
            if (value is int) n = (int)value;
            else if (value is long) n = (long)value;
            else throw new BridgeException("invalid_argument", key + " must be a whole number");
            if (n < min || n > max)
                throw new BridgeException("invalid_argument", key + " must be between " + min + " and " + max);
            return (int)n;
        }

        // A required absolute path on a drive (C:\...), normalised. A drive-relative path (C:file)
        // or a root-relative one (\file) would resolve against the bridge's working directory,
        // which no request names, so both are refused. A network path (\\server\share\...) is
        // accepted only where the operation lets the caller allow it; device and \\?\ paths never.
        public string FullPath(string key)
        {
            return FullPath(key, false);
        }

        public string FullPath(string key, bool allowNetwork)
        {
            string s = String(key, null);
            if (string.IsNullOrEmpty(s)) throw new BridgeException("invalid_argument", key + " is required");
            // Path.GetInvalidPathChars covers control characters, quotes, < > and |.
            if (s.Length > 32000 || s.IndexOfAny(Path.GetInvalidPathChars()) >= 0 || s.IndexOfAny(new char[] { '*', '?' }) >= 0)
                throw new BridgeException("invalid_argument", key + " is not a valid path");
            if (!OnDrive(s) && !(allowNetwork && Network(s)))
                throw new BridgeException("invalid_argument", key + (Network(s)
                    ? " is a network path, which this request does not allow"
                    : " must be an absolute path on a drive, such as C:\\folder\\file"));
            string full;
            try { full = Path.GetFullPath(s); }
            catch (Exception e) { throw new BridgeException("invalid_argument", key + " is not a valid path: " + e.Message); }
            // Normalising may turn a name into a device path; check the result again.
            if (!OnDrive(full) && !(allowNetwork && Network(full)))
                throw new BridgeException("invalid_argument", key + " is not a valid path");
            return full;
        }

        static bool Separator(char c)
        {
            return c == '\\' || c == '/';
        }

        static bool OnDrive(string s)
        {
            return s.Length >= 3 && ((s[0] >= 'A' && s[0] <= 'Z') || (s[0] >= 'a' && s[0] <= 'z')) && s[1] == ':' && Separator(s[2]);
        }

        // \\server\share\..., but not \\?\ or \\.\ (device and raw paths).
        static bool Network(string s)
        {
            return s.Length > 2 && Separator(s[0]) && Separator(s[1]) && s[2] != '?' && s[2] != '.' && !Separator(s[2]);
        }
    }

    delegate Dictionary<string, object> Handler(Args args);

    static class Bridge
    {
        [DllImport("kernel32.dll")]
        static extern uint SetErrorMode(uint mode);

        static readonly Dictionary<string, Handler> handlers = new Dictionary<string, Handler>();
        static bool filterRegistered, stopping;

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static int Run()
        {
            SetErrorMode(0x8003); // no crash or critical-error dialogs from this process
            Output.Open();
            filterRegistered = MessageFilter.Register();
            handlers["hello"] = Hello;
            handlers["shutdown"] = Shutdown;
            Operations.Register(handlers);
            if (Program.TestOps)
            {
                handlers["sleep"] = TestSleep;
                handlers["exit"] = TestExit;
                handlers["emit"] = TestEmit;
                handlers["classify_windows"] = TestClassifyWindows;
                handlers["watch_timing"] = TestWatchTiming;
            }
            if (Program.TestSession) Operations.RegisterTestSession(handlers);

            LineReader reader = new LineReader();
            reader.Start(Console.OpenStandardInput());
            Dictionary<string, object> ready = Describe();
            ready["event"] = "ready";
            int code = 0;
            try
            {
                Output.Send(ready);
                while (!stopping)
                {
                    LineReader.Line line = reader.Next();
                    if (line.End) break;
                    Output.Send(Handle(line));
                }
            }
            catch (IOException e)
            {
                Console.Error.WriteLine("standard output closed: " + e.Message);
                code = 1;
            }
            finally
            {
                // Let go of a session the bridge attached to, never ending it, and end the
                // SOLIDWORKS this bridge started, however the conversation ended. No client is left
                // to ask again, so a document a person opened in it is not waited for here.
                Request.Begin(60);
                try { Operations.DetachLive(); }
                catch (Exception e) { Console.Error.WriteLine("detaching: " + e.Message); }
                try { Operations.EndSolidWorks(30000); }
                catch (Exception e) { Console.Error.WriteLine("ending SOLIDWORKS: " + e.Message); }
                // The last reply (shutdown's) may still be in the writer's queue.
                Output.Drain(5000);
            }
            return code;
        }

        static Dictionary<string, object> Handle(LineReader.Line line)
        {
            object id = null;
            Dictionary<string, object> reply = new Dictionary<string, object>();
            try
            {
                if (line.TooLong) throw new BridgeException("bad_request", "request longer than " + LineReader.MaxLine + " characters");
                object parsed;
                try { parsed = Json.Parse(line.Text); }
                catch (Exception e) { throw new BridgeException("bad_request", "not JSON: " + e.Message); }
                Dictionary<string, object> request = parsed as Dictionary<string, object>;
                if (request == null) throw new BridgeException("bad_request", "a request is a JSON object");
                object rawId;
                if (request.TryGetValue("id", out rawId) && (rawId is int || rawId is long)) id = rawId;
                else throw new BridgeException("bad_request", "id must be a whole number");
                foreach (string key in request.Keys)
                {
                    if (key != "id" && key != "op" && key != "args" && key != "timeout_s")
                        throw new BridgeException("bad_request", "unknown request field: " + key);
                }
                object rawOp, rawArgs, rawTimeout;
                request.TryGetValue("op", out rawOp);
                string op = rawOp as string;
                if (op == null) throw new BridgeException("bad_request", "op must be a string");
                request.TryGetValue("args", out rawArgs);
                if (rawArgs != null && !(rawArgs is Dictionary<string, object>))
                    throw new BridgeException("bad_request", "args must be a JSON object");
                double timeout = 600;
                if (request.TryGetValue("timeout_s", out rawTimeout) && rawTimeout != null)
                {
                    if (rawTimeout is int) timeout = (int)rawTimeout;
                    else if (rawTimeout is long) timeout = (long)rawTimeout;
                    else if (rawTimeout is decimal) timeout = (double)(decimal)rawTimeout;
                    else throw new BridgeException("bad_request", "timeout_s must be a number");
                    if (timeout <= 0 || timeout > 86400) throw new BridgeException("bad_request", "timeout_s is out of range");
                }
                Handler handler;
                if (!handlers.TryGetValue(op, out handler)) throw new BridgeException("unknown_op", "no operation named " + op);
                Request.Begin(timeout);
                Dictionary<string, object> result = handler(new Args(rawArgs as Dictionary<string, object>));
                reply["id"] = id;
                reply["ok"] = true;
                reply["result"] = result ?? new Dictionary<string, object>();
                return reply;
            }
            catch (BridgeException e)
            {
                return Failure(id, e.Code, e.Message, null, e.Details);
            }
            catch (COMException e)
            {
                return Failure(id, Operations.Classify(e.ErrorCode), e.Message, e.ErrorCode, null);
            }
            catch (InvalidCastException e)
            {
                return Failure(id, "com_error", e.Message, null, null);
            }
            catch (Exception e)
            {
                return Failure(id, "internal", e.GetType().Name + ": " + e.Message, null, null);
            }
        }

        static Dictionary<string, object> Failure(object id, string code, string message, int? hresult, Dictionary<string, object> details)
        {
            Dictionary<string, object> error = new Dictionary<string, object>();
            error["code"] = code;
            error["message"] = message ?? "";
            if (hresult.HasValue) error["hresult"] = hresult.Value;
            if (details != null) error["details"] = details;
            Dictionary<string, object> reply = new Dictionary<string, object>();
            reply["id"] = id;
            reply["ok"] = false;
            reply["error"] = error;
            return reply;
        }

        static Dictionary<string, object> Describe()
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["protocol"] = Program.Protocol;
            d["bridge_version"] = Version();
            d["pid"] = System.Diagnostics.Process.GetCurrentProcess().Id;
            d["apartment"] = Thread.CurrentThread.GetApartmentState().ToString();
            d["message_filter"] = filterRegistered;
            d["in_job"] = Native.InAnyJob();
            d["test_ops"] = Program.TestOps;
            d["test_session"] = Program.TestSession;
            d["events_lost"] = Output.EventsLost;
            List<string> ops = new List<string>(handlers.Keys);
            ops.Sort(StringComparer.Ordinal);
            d["ops"] = ops;
            return d;
        }

        static string Version()
        {
            object[] attrs = typeof(Bridge).Assembly.GetCustomAttributes(typeof(AssemblyInformationalVersionAttribute), false);
            return attrs.Length > 0 ? ((AssemblyInformationalVersionAttribute)attrs[0]).InformationalVersion : "unknown";
        }

        static Dictionary<string, object> Hello(Args args)
        {
            args.Allow();
            Dictionary<string, object> d = Describe();
            d["solidworks"] = Operations.StartedPid();
            return d;
        }

        // Ends the SOLIDWORKS this bridge started, as exit_solidworks does, and then the bridge. Refused
        // the same way while SOLIDWORKS shows a document the bridge did not open, and the bridge
        // then keeps running.
        static Dictionary<string, object> Shutdown(Args args)
        {
            args.Allow();
            Dictionary<string, object> result = Operations.EndSolidWorks(Math.Max(1000, Request.RemainingMs()), true);
            stopping = true;
            return result;
        }

        // Test operations, only with --test-ops: a call that blocks the apartment thread
        // without pumping, as a call stuck inside SOLIDWORKS does, a crash, a burst of event
        // lines, as SOLIDWORKS notifications send them, the window rule applied to windows
        // described in the request, and the window watch's timing for the next start.
        static Dictionary<string, object> TestSleep(Args args)
        {
            args.Allow("ms");
            int ms = args.Int("ms", 1000, 0, 3600000);
            Thread.Sleep(ms);
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["slept_ms"] = ms;
            return d;
        }

        // Queues count event lines the way a notification handler does and says how long that
        // took: never longer because nobody reads standard output.
        static Dictionary<string, object> TestEmit(Args args)
        {
            args.Allow("count");
            int count = args.Int("count", 1, 0, 1000000);
            int start = Environment.TickCount;
            for (int i = 0; i < count; i++)
            {
                Dictionary<string, object> e = new Dictionary<string, object>();
                e["event"] = "test";
                e["n"] = i;
                Output.Event(e);
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["emitted"] = count;
            d["ms"] = unchecked(Environment.TickCount - start);
            return d;
        }

        // The rule the window watch applies to real windows (WindowRule.Classify), applied to a
        // list of described windows, with job_pids standing in for the processes in the bridge's
        // Job Object and own_pid for the SLDWORKS.exe it started, and each window's image for its
        // process's program: the verdict for each window.
        static Dictionary<string, object> TestClassifyWindows(Args args)
        {
            args.Allow("own_pid", "job_pids", "windows");
            int ownPid = args.Int("own_pid", 0, 1, int.MaxValue);
            List<int> job = new List<int>();
            foreach (object item in args.List("job_pids")) job.Add(Args.WholeNumber(item, "job_pids"));
            Func<int, bool> inJob = delegate(int pid) { return job.Contains(pid); };
            List<object> verdicts = new List<object>();
            foreach (object item in args.List("windows"))
            {
                Args w = Args.Item(item, "windows");
                w.Allow("hwnd", "pid", "image", "class", "title", "visible", "children");
                WindowInfo info = new WindowInfo();
                info.Handle = w.Int("hwnd", 0, 0, int.MaxValue);
                info.ProcessId = w.Int("pid", 0, 0, int.MaxValue);
                info.Image = w.String("image", "");
                info.ClassName = w.String("class", "");
                info.Title = w.String("title", "");
                info.Visible = w.Bool("visible", true);
                foreach (object c in w.List("children"))
                {
                    Args child = Args.Item(c, "children");
                    child.Allow("class", "text");
                    info.Children.Add(new KeyValuePair<string, string>(child.String("class", ""), child.String("text", "")));
                }
                Dictionary<string, object> v = new Dictionary<string, object>();
                v["hwnd"] = info.Handle;
                v["verdict"] = WindowRule.Classify(info, inJob, ownPid);
                v["text"] = WindowRule.Text(info);
                verdicts.Add(v);
            }
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["verdicts"] = verdicts;
            return d;
        }

        // Sets how the window watch of the next start_solidworks looks: its fast phase ends fast_ms
        // after it starts, registered or not, and it then waits slow_ms between looks unless the
        // WinEvent hook wakes it. A stand-in SOLIDWORKS never registers, so without this the watch
        // would look every 100 ms for the whole test and never depend on the hook.
        static Dictionary<string, object> TestWatchTiming(Args args)
        {
            args.Allow("fast_ms", "slow_ms");
            int fast = args.Int("fast_ms", 0, 0, 600000);
            int slow = args.Int("slow_ms", 1000, 100, 600000);
            WindowWatch.TestFastPhaseMs = fast;
            WindowWatch.TestSlowMs = slow;
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["fast_ms"] = WindowWatch.TestFastPhaseMs;
            d["slow_ms"] = WindowWatch.TestSlowMs;
            return d;
        }

        static Dictionary<string, object> TestExit(Args args)
        {
            args.Allow("code");
            Environment.Exit(args.Int("code", 3, 0, 255));
            return null;
        }
    }
}
