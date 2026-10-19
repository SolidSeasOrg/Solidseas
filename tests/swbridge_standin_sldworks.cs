// A stand-in for SLDWORKS.exe that shows dialogs, for the opt-in window test in test_swapi.py.
//
// The test compiles it, with the .NET Framework's csc.exe, as SLDWORKS.exe in two folders: the
// bridge starts one copy in its Job Object, as it starts SolidSeas' own SOLIDWORKS, and the
// test starts the other itself, playing the user's SOLIDWORKS. It is also compiled as
// swactwiz.exe, playing SOLIDWORKS Product Activation, which a SOLIDWORKS that is not
// activated starts at start-up and waits for. Each copy reads standin.txt next to itself, one
// step per line:
//
//   show|<milliseconds to wait>|<title>|<static text>|<window class of one more child, or nothing>
//   reshow|<milliseconds to wait>|<number of a dialog shown before, from 0>
//   start|<milliseconds to wait>|<a program, by its path from this folder>
//
// A program it starts is its child, so it is in the same Job Object, as the programs a real
// SOLIDWORKS starts are.
//
// After each step it appends "<step> <dialog number> <GetTickCount>" to standin.log next to
// itself (for start, the process id of the program started in place of the dialog number), so
// a test can tell how soon after a step the bridge acted.
//
// A dialog is a top-level window of class #32770 holding an empty static (where a message box
// has its icon), a static text and an OK button, as a message box does. Every dialog is shown
// without being activated, at -32000,-32000, off every screen, so nothing reaches the screen of
// the person at the machine. It never registers in the Running Object Table, so the bridge's
// start_solidworks waits for it until its timeout and then ends it.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

static class StandIn
{
    const int WS_POPUP = unchecked((int)0x80000000), WS_CAPTION = 0x00C00000, WS_CHILD = 0x40000000, WS_VISIBLE = 0x10000000;
    const int WS_EX_TOOLWINDOW = 0x00000080, WS_EX_NOACTIVATE = 0x08000000;
    const int SW_SHOWNOACTIVATE = 4;
    const uint QS_ALLINPUT = 0x04FF, PM_REMOVE = 1, WAIT_TIMEOUT = 258;

    [StructLayout(LayoutKind.Sequential)]
    struct Msg
    {
        public IntPtr hwnd;
        public uint message;
        public IntPtr wParam, lParam;
        public uint time;
        public int x, y;
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CreateWindowEx(int exStyle, string className, string name, int style, int x, int y, int width,
        int height, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
    [DllImport("user32.dll")]
    static extern bool ShowWindow(IntPtr hwnd, int command);
    [DllImport("user32.dll")]
    static extern uint MsgWaitForMultipleObjects(uint count, IntPtr[] handles, bool all, uint milliseconds, uint wakeMask);
    [DllImport("user32.dll")]
    static extern bool PeekMessage(out Msg msg, IntPtr hwnd, uint min, uint max, uint remove);
    [DllImport("user32.dll")]
    static extern bool TranslateMessage(ref Msg msg);
    [DllImport("user32.dll")]
    static extern IntPtr DispatchMessage(ref Msg msg);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr GetModuleHandle(string name);

    // Dispatches messages for the time given; a negative time, for ever.
    static void Pump(int milliseconds)
    {
        int start = Environment.TickCount;
        while (true)
        {
            uint wait = 0xFFFFFFFF;
            if (milliseconds >= 0)
            {
                int left = milliseconds - unchecked(Environment.TickCount - start);
                if (left <= 0) return;
                wait = (uint)left;
            }
            if (MsgWaitForMultipleObjects(0, new IntPtr[0], false, wait, QS_ALLINPUT) == WAIT_TIMEOUT) continue;
            Msg msg;
            while (PeekMessage(out msg, IntPtr.Zero, 0, 0, PM_REMOVE))
            {
                TranslateMessage(ref msg);
                DispatchMessage(ref msg);
            }
        }
    }

    static void Note(string log, string step, int dialog)
    {
        File.AppendAllText(log, step + " " + dialog + " " + unchecked((uint)Environment.TickCount) + "\n");
    }

    [STAThread]
    static int Main()
    {
        IntPtr instance = GetModuleHandle(null);
        string[] steps = File.ReadAllLines(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "standin.txt"));
        string log = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "standin.log");
        List<IntPtr> dialogs = new List<IntPtr>();
        foreach (string line in steps)
        {
            string[] f = line.Split('|');
            if (f.Length < 3) continue;
            Pump(int.Parse(f[1]));
            if (f[0] == "show")
            {
                int n = dialogs.Count;
                IntPtr dialog = CreateWindowEx(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "#32770", f[2], WS_POPUP | WS_CAPTION,
                                               -32000 + 400 * n, -32000, 380, 160, IntPtr.Zero, IntPtr.Zero, instance, IntPtr.Zero);
                if (dialog == IntPtr.Zero) return 1;
                CreateWindowEx(0, "Static", "", WS_CHILD | WS_VISIBLE, 10, 10, 32, 32, dialog, (IntPtr)20, instance, IntPtr.Zero);
                CreateWindowEx(0, "Static", f.Length > 3 ? f[3] : "", WS_CHILD | WS_VISIBLE, 50, 10, 320, 80, dialog,
                               (IntPtr)0xFFFF, instance, IntPtr.Zero);
                CreateWindowEx(0, "Button", "OK", WS_CHILD | WS_VISIBLE, 150, 100, 80, 24, dialog, (IntPtr)1, instance, IntPtr.Zero);
                if (f.Length > 4 && f[4].Length > 0)
                    CreateWindowEx(0, f[4], "", WS_CHILD | WS_VISIBLE, 10, 100, 120, 24, dialog, (IntPtr)30, instance, IntPtr.Zero);
                ShowWindow(dialog, SW_SHOWNOACTIVATE);
                dialogs.Add(dialog);
                Note(log, "show", n);
            }
            else if (f[0] == "reshow")
            {
                int n = int.Parse(f[2]);
                ShowWindow(dialogs[n], SW_SHOWNOACTIVATE);
                Note(log, "reshow", n);
            }
            else if (f[0] == "start")
            {
                ProcessStartInfo start = new ProcessStartInfo(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, f[2]));
                start.UseShellExecute = false;
                start.WorkingDirectory = Path.GetDirectoryName(start.FileName);
                using (Process child = Process.Start(start)) Note(log, "start", child.Id);
            }
        }
        Pump(-1);
        return 0;
    }
}
