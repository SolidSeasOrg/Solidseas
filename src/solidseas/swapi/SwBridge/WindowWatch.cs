// The windows of SolidSeas' own SOLIDWORKS, and the one message box the bridge hides.
//
// While another SOLIDWORKS runs on the machine, the instance the bridge starts opens a
// message box, titled SOLIDWORKS, that reads "A journal file could not be created. Auto
// recover will not work. Another session of SOLIDWORKS may already be running on this
// machine." Hiding the instance does not hide it; it stays until the instance ends, and it
// took the foreground of the user's desktop again as other windows came and went (measured
// with SOLIDWORKS 2024 SP1). The user chose to have the bridge hide that box, and only that
// box, of its own instance.
//
// The watch looks at the windows of every process in the bridge's Job Object: the
// SLDWORKS.exe it started and whatever that process started. Each process other than
// SLDWORKS.exe is taken as one of them only through a handle of the watch's own, opened for
// that look, through which it is checked to be in the job and still running; the handle
// keeps its id from passing to another process while its windows are read.
//
// A window is hidden only when all of this holds (WindowRule.Classify):
// - its process is the SLDWORKS.exe this bridge started and holds in its Job Object: the
//   window's process id is that process's (the bridge keeps a handle on it, so the id cannot
//   pass to another process), and that process is a member of the job;
// - it is a visible top-level dialog (window class #32770) whose title names SOLIDWORKS;
// - every window inside it is a static text or a button, as in a message box, and one static
//   text holds the stable words of the journal message.
// A window of a process outside the job is never looked at past its process id. Hiding is one
// ShowWindow(SW_HIDE) call, and the box goes when the instance ends: the bridge never clicks,
// closes or activates it or sends it a message of its own. Windows sends the box the usual
// notifications of being hidden and, if the box was the foreground window, activates another
// window, normally the one the user was in. Every other visible dialog of a process in the job
// is left as it is and reported once; a SOLIDWORKS call it blocks is ended by the caller's
// timeout, as before.
//
// One of those is SOLIDWORKS Product Activation. A SOLIDWORKS that is not activated on the PC
// starts swactwiz.exe at start-up ("/primprod:solidworks /auto /expirycheck") and waits for it
// while it shows its wizard, so the instance never registers (measured with SOLIDWORKS 2024
// SP1, 2026-10-14: "There are 0 day(s) left in your grace period", the choice to activate
// later disabled). A visible dialog of swactwiz.exe in the job is reported as the kind
// "activation" and left as it is, like any other: nothing SolidSeas runs answers that wizard,
// since a wrong choice there can move a standalone licence away. start_solidworks then fails
// at once with solidworks_not_activated and ends the instance, the wizard with it.
//
// The watch runs on a thread of its own, so it works while the apartment thread is inside a
// SOLIDWORKS call. It looks every 100 ms from the moment the process starts until a minute
// after the instance registers, and after that every second and at once whenever a window of
// SLDWORKS.exe is shown (a WinEvent hook for that process alone); the other processes' windows
// are found by the looks. It keeps the dialogs it left, so a request can say which appeared
// while it ran (import_file) or why it failed (start_solidworks).
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace SolidSeas.SwBridge
{
    // What the watch reads about one top-level window. The program, class name, title and
    // children are read only for a window of a process in the bridge's Job Object.
    sealed class WindowInfo
    {
        public long Handle;
        public int ProcessId;
        public string Image = ""; // the file name of the process's program, "swactwiz.exe"
        public string ClassName = "";
        public string Title = "";
        public bool Visible;
        public readonly List<KeyValuePair<string, string>> Children = new List<KeyValuePair<string, string>>();
    }

    // The rule that picks the journal file message box, and SOLIDWORKS Product Activation, out of
    // everything else.
    static class WindowRule
    {
        public const string Hide = "hide";               // the journal file message box of the bridge's own SOLIDWORKS
        public const string Activation = "activation";   // SOLIDWORKS Product Activation asking: left, reported, the start fails
        public const string Leave = "leave";             // another visible dialog of a process in the job: left, and reported
        public const string NotOurs = "not_ours";        // any window of a process outside the job: never touched
        public const string NotADialog = "not_a_dialog";
        public const string NotShown = "not_shown";

        public const string DialogClass = "#32770";
        // The program a SOLIDWORKS that is not activated starts, and waits for, at start-up.
        public const string ActivationProgram = "swactwiz.exe";

        // Stable words of the journal message, compared ignoring case, with every run of white
        // space read as one space. A SOLIDWORKS in another language does not match, and its box
        // is left alone.
        static readonly string[] JournalWords = { "journal file", "could not be created", "another session of solidworks" };

        // inJob says whether a process id is a process in the bridge's Job Object, still running:
        // the SLDWORKS.exe it started (ownPid) or one that process started. It is asked before
        // anything else about the window is looked at. Only ownPid's journal box is ever hidden.
        public static string Classify(WindowInfo w, Func<int, bool> inJob, int ownPid)
        {
            if (!inJob(w.ProcessId)) return NotOurs;
            if (!string.Equals(w.ClassName, DialogClass, StringComparison.Ordinal)) return NotADialog;
            if (!w.Visible) return NotShown;
            if (w.ProcessId != ownPid && string.Equals(w.Image, ActivationProgram, StringComparison.OrdinalIgnoreCase))
                return Activation;
            return w.ProcessId == ownPid && IsJournalBox(w) ? Hide : Leave;
        }

        static bool IsJournalBox(WindowInfo w)
        {
            if (w.Title == null || w.Title.IndexOf("SOLIDWORKS", StringComparison.OrdinalIgnoreCase) < 0) return false;
            bool found = false;
            foreach (KeyValuePair<string, string> child in w.Children)
            {
                bool isStatic = string.Equals(child.Key, "Static", StringComparison.OrdinalIgnoreCase);
                if (!isStatic && !string.Equals(child.Key, "Button", StringComparison.OrdinalIgnoreCase)) return false;
                if (isStatic && HasJournalWords(child.Value)) found = true;
            }
            return found;
        }

        public static bool HasJournalWords(string text)
        {
            if (string.IsNullOrEmpty(text)) return false;
            string t = Normalise(text);
            foreach (string words in JournalWords)
            {
                if (t.IndexOf(words, StringComparison.Ordinal) < 0) return false;
            }
            return true;
        }

        static string Normalise(string text)
        {
            StringBuilder b = new StringBuilder(text.Length);
            bool space = false;
            foreach (char c in text)
            {
                if (char.IsWhiteSpace(c))
                {
                    space = true;
                    continue;
                }
                if (space && b.Length > 0) b.Append(' ');
                space = false;
                b.Append(char.ToLowerInvariant(c));
            }
            return b.ToString();
        }

        // The static texts of a window, for the log: the journal message alone when it is there.
        public static string Text(WindowInfo w)
        {
            List<string> texts = new List<string>();
            foreach (KeyValuePair<string, string> child in w.Children)
            {
                if (!string.Equals(child.Key, "Static", StringComparison.OrdinalIgnoreCase) || string.IsNullOrEmpty(child.Value)) continue;
                if (HasJournalWords(child.Value)) return child.Value;
                texts.Add(child.Value);
            }
            return string.Join(" | ", texts.ToArray());
        }
    }

    sealed class WindowWatch
    {
        const int FastMs = 100, SlowMs = 1000, AfterRegistrationMs = 60000, MinGapMs = 50;
        // Set only by the watch_timing test operation (with --test-ops), for the watches started
        // after it: the fast phase ends TestFastPhaseMs after the watch starts, registered or
        // not, and slow looks are TestSlowMs apart. Negative: the timing above.
        public static int TestFastPhaseMs = -1, TestSlowMs = -1;
        const int MaxChildren = 64, MaxText = 2048, MaxKept = 256, MaxJobProcesses = 64;
        const uint PROCESS_QUERY_LIMITED_INFORMATION = 0x1000, SYNCHRONIZE = 0x00100000;
        const int SW_HIDE = 0;
        const uint EVENT_OBJECT_SHOW = 0x8002, WINEVENT_OUTOFCONTEXT = 0;
        const int OBJID_WINDOW = 0, CHILDID_SELF = 0;

        delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);
        delegate void WinEventProc(IntPtr hook, uint eventType, IntPtr hwnd, int idObject, int idChild, uint thread, uint time);

        [DllImport("user32.dll")]
        static extern bool EnumWindows(EnumProc callback, IntPtr lParam);
        [DllImport("user32.dll")]
        static extern bool EnumChildWindows(IntPtr parent, EnumProc callback, IntPtr lParam);
        [DllImport("user32.dll")]
        static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        static extern int GetClassName(IntPtr hwnd, StringBuilder name, int size);
        // For a window of another process this reads the text the window manager keeps; it sends
        // the window no message.
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int size);
        [DllImport("user32.dll")]
        static extern bool IsWindowVisible(IntPtr hwnd);
        [DllImport("user32.dll")]
        static extern bool ShowWindow(IntPtr hwnd, int command);
        [DllImport("user32.dll")]
        static extern IntPtr SetWinEventHook(uint eventMin, uint eventMax, IntPtr module, WinEventProc callback, uint processId,
            uint threadId, uint flags);
        [DllImport("user32.dll")]
        static extern bool UnhookWinEvent(IntPtr hook);

        readonly int pid;
        readonly string image; // SLDWORKS.exe's file name, as it was started
        readonly bool inJob;
        readonly int fastPhaseMs, slowMs, startedAt;
        IntPtr process; // the watch's own handle on the process: its id stays that process's while open
        IntPtr job; // the watch's own handle on the bridge's job, to read which processes are in it
        // The other processes in the job during one look: a handle of the watch's own on each,
        // checked to be in the job through it, and its program's file name.
        readonly Dictionary<int, IntPtr> members = new Dictionary<int, IntPtr>();
        readonly Dictionary<int, string> memberImages = new Dictionary<int, string>();
        // The first SOLIDWORKS Product Activation dialog seen, as reported; null until then.
        Dictionary<string, object> activation;
        readonly AutoResetEvent wake = new AutoResetEvent(false);
        readonly Thread thread;
        volatile bool stopping, registered;
        volatile int registeredAt;
        int hidden;
        // Windows already reported, by handle: what was done, so each is logged once.
        readonly Dictionary<IntPtr, string> reported = new Dictionary<IntPtr, string>();
        readonly EnumProc collectOwn, collectChild;
        readonly WinEventProc onShow; // kept here: the hook calls it for as long as it is set
        readonly List<IntPtr> found = new List<IntPtr>();
        List<KeyValuePair<string, string>> children;
        // The dialogs left as they are, in the order they were first seen (the last MaxKept),
        // how many there have been, and how many looks the watch has finished.
        readonly List<Dictionary<string, object>> leftDialogs = new List<Dictionary<string, object>>();
        int leftTotal, scans;
        readonly AutoResetEvent scanned = new AutoResetEvent(false);

        WindowWatch(int pid, string image, IntPtr process, IntPtr job, bool inJob)
        {
            this.pid = pid;
            this.image = image;
            this.process = process;
            this.job = job;
            this.inJob = inJob;
            fastPhaseMs = TestFastPhaseMs;
            slowMs = TestSlowMs > 0 ? TestSlowMs : SlowMs;
            startedAt = Environment.TickCount;
            collectOwn = CollectOwn;
            collectChild = CollectChild;
            onShow = OnShow;
            thread = new Thread(Run);
            thread.IsBackground = true;
            thread.Name = "windows";
        }

        // Starts watching the windows of the process the bridge started, or returns null (and the
        // instance's windows are left alone) when that process is not provably its own.
        public static WindowWatch Start(OwnedProcess owner)
        {
            if (!owner.InJob)
            {
                Console.Error.WriteLine("windows: SLDWORKS.exe (PID " + owner.Id + ") is not in this bridge's job; its windows are left alone");
                return null;
            }
            IntPtr copy = owner.DuplicateForWatching();
            if (copy == IntPtr.Zero)
            {
                Console.Error.WriteLine(Native.LastError("windows: DuplicateHandle") + "; its windows are left alone");
                return null;
            }
            IntPtr job = owner.DuplicateJobForWatching();
            if (job == IntPtr.Zero)
                Console.Error.WriteLine(Native.LastError("windows: DuplicateHandle of the job") +
                                        "; only the windows of SLDWORKS.exe itself are looked at");
            // A process never leaves a job, so membership checked here holds for as long as the
            // watch's handle keeps the id from passing to another process.
            WindowWatch watch = new WindowWatch(owner.Id, Path.GetFileName(owner.Exe), copy, job, true);
            if (watch.fastPhaseMs >= 0)
                Console.Error.WriteLine("windows: test timing: every " + FastMs + " ms for " + watch.fastPhaseMs + " ms, then every " + watch.slowMs + " ms and when the hook says");
            watch.thread.Start();
            return watch;
        }

        // The instance has registered: look quickly for one more minute, then settle.
        public void Registered()
        {
            registeredAt = Environment.TickCount;
            registered = true;
            wake.Set();
        }

        public int Hidden
        {
            get { return Thread.VolatileRead(ref hidden); }
        }

        public bool Running
        {
            get { return thread.IsAlive; }
        }

        // How many dialogs the watch has left as they are so far: a request notes it when it starts.
        public int DialogsSeen
        {
            get { lock (leftDialogs) return leftTotal; }
        }

        // The first SOLIDWORKS Product Activation dialog the watch saw (hwnd, pid, process, class,
        // title, text), or null when none has shown.
        public Dictionary<string, object> Activation
        {
            get
            {
                lock (leftDialogs) return activation == null ? null : new Dictionary<string, object>(activation);
            }
        }

        // Has the watch look again (for at most lookMs), so a dialog showing now is counted, and
        // returns the dialogs it left after the first `since`: hwnd, class, title and text.
        public List<object> DialogsSince(int since, int lookMs)
        {
            LookAgain(lookMs);
            List<object> list = new List<object>();
            lock (leftDialogs)
            {
                int first = leftTotal - leftDialogs.Count;
                for (int i = Math.Max(since, first); i < leftTotal; i++)
                    list.Add(new Dictionary<string, object>(leftDialogs[i - first]));
            }
            return list;
        }

        // Waits, dispatching messages, until the watch has finished two more looks: the one under
        // way may have started before the window was shown.
        void LookAgain(int milliseconds)
        {
            int target = Thread.VolatileRead(ref scans) + 2;
            int start = Environment.TickCount;
            while (thread.IsAlive && Thread.VolatileRead(ref scans) < target)
            {
                int remaining = milliseconds - unchecked(Environment.TickCount - start);
                if (remaining <= 0) return;
                wake.Set();
                Pump.Wait(scanned.SafeWaitHandle.DangerousGetHandle(), Math.Min(remaining, 100));
            }
        }

        public void Stop(int milliseconds)
        {
            stopping = true;
            wake.Set();
            if (!thread.Join(milliseconds)) Console.Error.WriteLine("windows: the watch did not stop in time");
        }

        bool Exited()
        {
            return Native.WaitForSingleObject(process, 0) == 0;
        }

        bool Fast
        {
            get
            {
                if (fastPhaseMs >= 0) return unchecked(Environment.TickCount - startedAt) < fastPhaseMs;
                return !registered || unchecked(Environment.TickCount - registeredAt) < AfterRegistrationMs;
            }
        }

        // The SLDWORKS.exe the bridge started, in its job, and still running.
        bool OwnProcess(int processId)
        {
            return processId == pid && inJob && !Exited();
        }

        // A process in the bridge's job, still running: SLDWORKS.exe, or one this look holds a
        // handle on that was checked to be in the job through it.
        bool InJob(int processId)
        {
            if (processId == pid) return OwnProcess(processId);
            IntPtr member;
            return members.TryGetValue(processId, out member) && Native.WaitForSingleObject(member, 0) != 0;
        }

        // Takes a handle of the watch's own on each other process in the job, for this look.
        void OpenMembers()
        {
            if (job == IntPtr.Zero) return;
            List<int> ids = Native.JobProcessIds(job, MaxJobProcesses);
            if (ids == null) return;
            foreach (int id in ids)
            {
                if (id == pid || members.ContainsKey(id)) continue;
                IntPtr h = Native.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, false, id);
                if (h == IntPtr.Zero) continue;
                bool inThisJob;
                // Checked through the handle: an id that passed to another process since the job
                // was read names a process outside the job, and is not taken.
                if (Native.IsProcessInJob(h, job, out inThisJob) && inThisJob && Native.WaitForSingleObject(h, 0) != 0)
                {
                    members[id] = h;
                    memberImages[id] = Native.ImageName(h);
                }
                else
                {
                    Native.CloseHandle(h);
                }
            }
        }

        void CloseMembers()
        {
            foreach (IntPtr h in members.Values) Native.CloseHandle(h);
            members.Clear();
            memberImages.Clear();
        }

        void Run()
        {
            IntPtr hook = IntPtr.Zero;
            try
            {
                hook = SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, IntPtr.Zero, onShow, (uint)pid, 0, WINEVENT_OUTOFCONTEXT);
                if (hook == IntPtr.Zero) Console.Error.WriteLine("windows: no WinEvent hook; looking every second instead");
                IntPtr woken = wake.SafeWaitHandle.DangerousGetHandle();
                while (!stopping && !Exited())
                {
                    int lookedAt = Environment.TickCount;
                    Scan();
                    Interlocked.Increment(ref scans);
                    scanned.Set();
                    // The hook's callback runs while this waits, and wakes it; a burst of shown
                    // windows is looked at no more often than every MinGapMs.
                    Pump.Wait(woken, Fast ? FastMs : slowMs);
                    int since = unchecked(Environment.TickCount - lookedAt);
                    if (since < MinGapMs) Pump.Sleep(MinGapMs - since);
                }
            }
            catch (Exception e)
            {
                Console.Error.WriteLine("windows: the watch stopped: " + e.Message);
            }
            finally
            {
                if (hook != IntPtr.Zero) UnhookWinEvent(hook);
                CloseMembers();
                if (job != IntPtr.Zero) Native.CloseHandle(job);
                job = IntPtr.Zero;
                Native.CloseHandle(process);
                process = IntPtr.Zero;
            }
        }

        void OnShow(IntPtr hook, uint eventType, IntPtr hwnd, int idObject, int idChild, uint threadId, uint time)
        {
            if (idObject == OBJID_WINDOW && idChild == CHILDID_SELF) wake.Set();
        }

        bool CollectOwn(IntPtr hwnd, IntPtr lParam)
        {
            uint owner;
            GetWindowThreadProcessId(hwnd, out owner);
            if (owner == (uint)pid || members.ContainsKey((int)owner)) found.Add(hwnd);
            return true;
        }

        bool CollectChild(IntPtr hwnd, IntPtr lParam)
        {
            children.Add(new KeyValuePair<string, string>(ClassOf(hwnd), TextOf(hwnd)));
            return children.Count < MaxChildren;
        }

        void Scan()
        {
            found.Clear();
            OpenMembers();
            try
            {
                EnumWindows(collectOwn, IntPtr.Zero);
                // Forget windows that are gone; a handle can be used again for another window.
                foreach (IntPtr gone in new List<IntPtr>(reported.Keys))
                {
                    if (!found.Contains(gone)) reported.Remove(gone);
                }
                foreach (IntPtr hwnd in new List<IntPtr>(found))
                {
                    WindowInfo w = Describe(hwnd);
                    string verdict = WindowRule.Classify(w, InJob, pid);
                    if (verdict == WindowRule.Hide) HideBox(hwnd, w);
                    else if (verdict == WindowRule.Leave || verdict == WindowRule.Activation) Report(hwnd, w, verdict);
                }
            }
            finally
            {
                CloseMembers();
            }
        }

        // Reads no further than the process id for a window of a process outside the job.
        WindowInfo Describe(IntPtr hwnd)
        {
            WindowInfo w = new WindowInfo();
            w.Handle = hwnd.ToInt64();
            uint owner;
            GetWindowThreadProcessId(hwnd, out owner);
            w.ProcessId = (int)owner;
            if (!InJob(w.ProcessId)) return w;
            w.Image = w.ProcessId == pid ? image : memberImages[w.ProcessId];
            w.ClassName = ClassOf(hwnd);
            w.Visible = IsWindowVisible(hwnd);
            if (w.ClassName != WindowRule.DialogClass || !w.Visible) return w;
            w.Title = TextOf(hwnd);
            children = w.Children;
            EnumChildWindows(hwnd, collectChild, IntPtr.Zero);
            children = null;
            return w;
        }

        void HideBox(IntPtr hwnd, WindowInfo w)
        {
            // Checked again right before the call: still a window of the bridge's own SOLIDWORKS.
            uint owner;
            GetWindowThreadProcessId(hwnd, out owner);
            if (!OwnProcess((int)owner)) return;
            ShowWindow(hwnd, SW_HIDE);
            Interlocked.Increment(ref hidden);
            Report(hwnd, w, WindowRule.Hide);
        }

        void Report(IntPtr hwnd, WindowInfo w, string verdict)
        {
            string before;
            reported.TryGetValue(hwnd, out before);
            if (verdict != WindowRule.Hide && before == verdict) return; // a dialog left is reported once
            bool again = verdict == WindowRule.Hide && before == WindowRule.Hide; // SOLIDWORKS showed it again
            reported[hwnd] = verdict;
            string text = WindowRule.Text(w);
            if (text.Length > MaxText) text = text.Substring(0, MaxText);
            string kind = verdict == WindowRule.Hide ? "journal_box" : verdict == WindowRule.Activation ? "activation" : "dialog";
            Dictionary<string, object> e = new Dictionary<string, object>();
            e["event"] = "window";
            e["action"] = verdict == WindowRule.Hide ? "hidden" : "left";
            e["kind"] = kind;
            e["pid"] = w.ProcessId;
            e["process"] = w.Image;
            e["hwnd"] = w.Handle;
            e["class"] = w.ClassName;
            e["title"] = w.Title;
            e["text"] = text;
            if (verdict == WindowRule.Hide) e["again"] = again;
            Output.Event(e);
            if (verdict != WindowRule.Hide)
            {
                Dictionary<string, object> kept = new Dictionary<string, object>();
                kept["hwnd"] = w.Handle;
                kept["pid"] = w.ProcessId;
                kept["process"] = w.Image;
                kept["kind"] = kind;
                kept["class"] = w.ClassName;
                kept["title"] = w.Title;
                kept["text"] = text;
                lock (leftDialogs)
                {
                    leftDialogs.Add(kept);
                    leftTotal++;
                    if (leftDialogs.Count > MaxKept) leftDialogs.RemoveAt(0);
                    if (verdict == WindowRule.Activation && activation == null) activation = new Dictionary<string, object>(kept);
                }
            }
            string what;
            if (verdict == WindowRule.Hide)
                what = (again ? "hid again" : "hid") + " the journal file message box of SOLIDWORKS (PID " + pid + ")";
            else if (verdict == WindowRule.Activation)
                what = "SOLIDWORKS Product Activation (" + w.Image + ", PID " + w.ProcessId +
                       ") is asking a question, which the bridge never answers; left as it is";
            else
                what = "left a dialog of " + (w.ProcessId == pid ? "SOLIDWORKS" : w.Image) + " (PID " + w.ProcessId + ") as it is";
            Console.Error.WriteLine("windows: " + what + ": window 0x" + w.Handle.ToString("X") +
                ", class " + w.ClassName + ", title \"" + w.Title + "\", text \"" + text + "\"");
        }

        static string ClassOf(IntPtr hwnd)
        {
            StringBuilder name = new StringBuilder(256);
            int n = GetClassName(hwnd, name, name.Capacity);
            return n > 0 ? name.ToString() : "";
        }

        static string TextOf(IntPtr hwnd)
        {
            StringBuilder text = new StringBuilder(MaxText + 1);
            int n = GetWindowText(hwnd, text, text.Capacity);
            return n > 0 ? text.ToString() : "";
        }
    }
}
