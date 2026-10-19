// Windows plumbing for the bridge: the Job Object that holds the SOLIDWORKS it starts and
// ends it, and file identity for the rule that a document is never written over.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace SolidSeas.SwBridge
{
    static class Native
    {
        [StructLayout(LayoutKind.Sequential)]
        public struct BasicLimits
        {
            public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass, SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct IoCounters
        {
            public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct ExtendedLimits
        {
            public BasicLimits Basic;
            public IoCounters Io;
            public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct BasicAccounting
        {
            public long TotalUserTime, TotalKernelTime, ThisPeriodTotalUserTime, ThisPeriodTotalKernelTime;
            public uint TotalPageFaultCount, TotalProcesses, ActiveProcesses, TotalTerminatedProcesses;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        public struct StartupInfo
        {
            public int cb;
            public string lpReserved, lpDesktop, lpTitle;
            public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
            public short wShowWindow, cbReserved2;
            public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct ProcessInformation
        {
            public IntPtr hProcess, hThread;
            public int dwProcessId, dwThreadId;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct ByHandleFileInformation
        {
            public uint FileAttributes;
            public uint CreationLow, CreationHigh, AccessLow, AccessHigh, WriteLow, WriteHigh;
            public uint VolumeSerialNumber, FileSizeHigh, FileSizeLow, NumberOfLinks, FileIndexHigh, FileIndexLow;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct FileIdInfo
        {
            public ulong VolumeSerialNumber;
            public ulong FileIdLow, FileIdHigh;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref ExtendedLimits info, int length);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool result);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool TerminateJobObject(IntPtr job, uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool QueryInformationJobObject(IntPtr job, int infoClass, out BasicAccounting info, int length,
            IntPtr returnLength);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool QueryInformationJobObject(IntPtr job, int infoClass, IntPtr info, int length, IntPtr returnLength);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern IntPtr OpenProcess(uint access, bool inherit, int processId);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool QueryFullProcessImageName(IntPtr process, int flags, StringBuilder name, ref int size);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool DuplicateHandle(IntPtr sourceProcess, IntPtr source, IntPtr targetProcess, out IntPtr target,
            uint access, bool inherit, uint options);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool CreateProcess(string application, StringBuilder commandLine, IntPtr processAttributes,
            IntPtr threadAttributes, bool inheritHandles, uint flags, IntPtr environment, string directory,
            ref StartupInfo startup, out ProcessInformation info);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern uint ResumeThread(IntPtr thread);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool TerminateProcess(IntPtr process, uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool GetExitCodeProcess(IntPtr process, out uint code);
        [DllImport("kernel32.dll")]
        public static extern IntPtr GetCurrentProcess();
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr security, uint disposition,
            uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetFileInformationByHandle(SafeFileHandle file, out ByHandleFileInformation info);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetFileInformationByHandleEx(SafeFileHandle file, int infoClass, out FileIdInfo info, int size);

        public static bool InAnyJob()
        {
            bool result;
            return IsProcessInJob(GetCurrentProcess(), IntPtr.Zero, out result) && result;
        }

        public static string LastError(string what)
        {
            return what + " failed: " + new Win32Exception(Marshal.GetLastWin32Error()).Message;
        }

        // The ids of the processes in a job (JobObjectBasicProcessIdList), at most max of them, or
        // null when the job cannot be read. A process that has exited is no longer listed.
        public static List<int> JobProcessIds(IntPtr job, int max)
        {
            const int BasicProcessIdList = 3, ERROR_MORE_DATA = 234;
            // Two DWORD counts, then the ids as ULONG_PTRs from offset 8 on 32 and 64-bit Windows alike.
            int size = 8 + max * IntPtr.Size;
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                Marshal.WriteInt64(buffer, 0, 0);
                if (!QueryInformationJobObject(job, BasicProcessIdList, buffer, size, IntPtr.Zero) &&
                    Marshal.GetLastWin32Error() != ERROR_MORE_DATA)
                    return null;
                int listed = Math.Min(Marshal.ReadInt32(buffer, 4), max);
                List<int> ids = new List<int>(listed);
                for (int i = 0; i < listed; i++) ids.Add((int)Marshal.ReadIntPtr(buffer, 8 + i * IntPtr.Size).ToInt64());
                return ids;
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        // The file name of a process's program ("swactwiz.exe"), from a handle on it, or "".
        public static string ImageName(IntPtr process)
        {
            StringBuilder name = new StringBuilder(1024);
            int size = name.Capacity;
            if (!QueryFullProcessImageName(process, 0, name, ref size)) return "";
            try
            {
                return Path.GetFileName(name.ToString(0, size));
            }
            catch (ArgumentException)
            {
                return "";
            }
        }

        // Which file a path names, whatever name reaches it (a junction, a hard link, a mapped
        // drive, a short name): the volume and the file id, or null when it cannot be opened.
        // Opening for attributes only never conflicts with SOLIDWORKS' own handles on the file.
        public static string FileIdentity(string path)
        {
            const uint FILE_READ_ATTRIBUTES = 0x80, SHARE_ALL = 0x7, OPEN_EXISTING = 3;
            const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;
            using (SafeFileHandle file = CreateFile(path, FILE_READ_ATTRIBUTES, SHARE_ALL, IntPtr.Zero, OPEN_EXISTING,
                                                    FILE_FLAG_BACKUP_SEMANTICS, IntPtr.Zero))
            {
                if (file.IsInvalid) return null;
                FileIdInfo id;
                if (GetFileInformationByHandleEx(file, 18 /* FileIdInfo */, out id, Marshal.SizeOf(typeof(FileIdInfo))))
                    return id.VolumeSerialNumber.ToString("X16") + ":" + id.FileIdHigh.ToString("X16") + id.FileIdLow.ToString("X16");
                ByHandleFileInformation info;
                if (GetFileInformationByHandle(file, out info))
                    return ((ulong)info.VolumeSerialNumber).ToString("X16") + ":" + info.FileIndexHigh.ToString("X8") + info.FileIndexLow.ToString("X8");
                return null;
            }
        }
    }

    // The SLDWORKS.exe this bridge started. It is created suspended, put in a Job Object with
    // kill-on-close before its first instruction runs, and only then resumed, so it can never
    // outlive the bridge: closing the job (the bridge exiting, or being ended) ends it. The job
    // is unnamed and the bridge puts nothing else in it, so it holds that process and what that
    // process starts, and nothing else; the bridge ends the instance by terminating the job.
    //
    // It starts on the user's desktop, and is seen there until it is hidden. SOLIDWORKS ignores
    // the show-window hint below: from about 0.3 s after it starts until it registers and the
    // bridge hides it (6 to 7 s), its splash screen and main window are the foreground window,
    // so keys and clicks meant for the user's own SOLIDWORKS reach this one; long batch jobs
    // therefore start it off-hours. While another SOLIDWORKS runs it also opens a message box
    // ("A journal file could not be created") that hiding the instance does not hide; the box
    // stays until the instance ends and took the foreground again as other windows came and went
    // (measured with SOLIDWORKS 2024 SP1), so the bridge hides that box itself (WindowWatch.cs).
    // A desktop of its own would keep all of that off the user's screen, but there SOLIDWORKS
    // stopped at that message box, which nobody can answer, and never registered.
    sealed class OwnedProcess
    {
        const uint CREATE_SUSPENDED = 0x4, CREATE_DEFAULT_ERROR_MODE = 0x04000000;
        const int STARTF_USESHOWWINDOW = 1;
        const short SW_SHOWMINNOACTIVE = 7;
        const int ExtendedLimitInformation = 9;
        const uint KillOnJobClose = 0x2000;

        const int BasicAccountingInformation = 1;

        public readonly int Id;
        public readonly string Exe;
        IntPtr handle;
        IntPtr job;

        OwnedProcess(int id, IntPtr handle, IntPtr job, string exe)
        {
            Id = id;
            this.handle = handle;
            this.job = job;
            Exe = exe;
        }

        public IntPtr Handle { get { return handle; } }

        public static OwnedProcess Start(string exe)
        {
            IntPtr job = Native.CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) throw new BridgeException("start_failed", Native.LastError("CreateJobObject"));
            Native.ExtendedLimits limits = new Native.ExtendedLimits();
            limits.Basic.LimitFlags = KillOnJobClose;
            if (!Native.SetInformationJobObject(job, ExtendedLimitInformation, ref limits, Marshal.SizeOf(typeof(Native.ExtendedLimits))))
            {
                string why = Native.LastError("SetInformationJobObject");
                Native.CloseHandle(job);
                throw new BridgeException("start_failed", why);
            }
            string commandLine = "\"" + exe + "\"";
            Native.StartupInfo startup = new Native.StartupInfo();
            startup.cb = Marshal.SizeOf(typeof(Native.StartupInfo));
            startup.dwFlags = STARTF_USESHOWWINDOW;
            startup.wShowWindow = SW_SHOWMINNOACTIVE; // asked for; SOLIDWORKS takes the foreground anyway (above)
            Native.ProcessInformation info;
            // No handles are inherited: SOLIDWORKS must not hold the bridge's pipes open.
            if (!Native.CreateProcess(exe, new StringBuilder(commandLine), IntPtr.Zero, IntPtr.Zero, false,
                                      CREATE_SUSPENDED | CREATE_DEFAULT_ERROR_MODE, IntPtr.Zero,
                                      Path.GetDirectoryName(exe), ref startup, out info))
            {
                string why = Native.LastError("CreateProcess");
                Native.CloseHandle(job);
                throw new BridgeException("start_failed", why);
            }
            if (!Native.AssignProcessToJobObject(job, info.hProcess))
            {
                string why = Native.LastError("AssignProcessToJobObject");
                Native.TerminateProcess(info.hProcess, 1); // still suspended: it never ran
                Native.WaitForSingleObject(info.hProcess, 10000);
                Native.CloseHandle(info.hThread);
                Native.CloseHandle(info.hProcess);
                Native.CloseHandle(job);
                throw new BridgeException("start_failed", why);
            }
            Native.ResumeThread(info.hThread);
            Native.CloseHandle(info.hThread);
            return new OwnedProcess(info.dwProcessId, info.hProcess, job, exe);
        }

        public bool HasExited
        {
            get { return Native.WaitForSingleObject(handle, 0) == 0; }
        }

        public bool WaitForExit(int milliseconds)
        {
            return Pump.Wait(handle, milliseconds);
        }

        public bool InJob
        {
            get
            {
                bool result;
                return Native.IsProcessInJob(handle, job, out result) && result;
            }
        }

        // Ends every process in this bridge's job, the SLDWORKS.exe it started and whatever that
        // process started, each with exitCode. Nothing else is in the job (above), so nothing else
        // is ever ended this way: a process outside it, the user's SOLIDWORKS among them, never is.
        public bool TerminateJob(uint exitCode)
        {
            return job != IntPtr.Zero && Native.TerminateJobObject(job, exitCode);
        }

        // How many processes in the job are still running, or -1 when that cannot be read.
        public int ActiveProcesses
        {
            get
            {
                if (job == IntPtr.Zero) return 0;
                Native.BasicAccounting info;
                if (!Native.QueryInformationJobObject(job, BasicAccountingInformation, out info,
                                                      Marshal.SizeOf(typeof(Native.BasicAccounting)), IntPtr.Zero))
                    return -1;
                return (int)info.ActiveProcesses;
            }
        }

        // A handle of the caller's own on this process, to wait on it and read its state; while it
        // is open, the process id stays this process's. IntPtr.Zero when it cannot be made.
        public IntPtr DuplicateForWatching()
        {
            const uint SYNCHRONIZE = 0x00100000, PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
            IntPtr copy;
            IntPtr self = Native.GetCurrentProcess();
            if (handle == IntPtr.Zero ||
                !Native.DuplicateHandle(self, handle, self, out copy, SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, false, 0))
                return IntPtr.Zero;
            return copy;
        }

        // A handle of the caller's own on this bridge's job, allowed only to read which processes
        // are in it; IntPtr.Zero when it cannot be made. The job outlives the handle's use.
        public IntPtr DuplicateJobForWatching()
        {
            const uint JOB_OBJECT_QUERY = 0x0004;
            IntPtr copy;
            IntPtr self = Native.GetCurrentProcess();
            if (job == IntPtr.Zero || !Native.DuplicateHandle(self, job, self, out copy, JOB_OBJECT_QUERY, false, 0))
                return IntPtr.Zero;
            return copy;
        }

        public uint ExitCode
        {
            get
            {
                uint code;
                return Native.GetExitCodeProcess(handle, out code) ? code : 0xFFFFFFFF;
            }
        }

        // Closing the job ends whatever is still in it, which is only what this bridge started.
        public void CloseJob()
        {
            if (job == IntPtr.Zero) return;
            Native.CloseHandle(job);
            job = IntPtr.Zero;
            Native.WaitForSingleObject(handle, 10000);
        }

        public void CloseHandle()
        {
            CloseJob();
            if (handle == IntPtr.Zero) return;
            Native.CloseHandle(handle);
            handle = IntPtr.Zero;
        }
    }
}
