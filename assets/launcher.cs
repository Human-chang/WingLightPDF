using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

public class SplashForm : Form
{
    private System.Windows.Forms.Timer animTimer;
    private System.Windows.Forms.Timer pollTimer;
    private Process childProc;
    private int barOffset = 0;
    private int elapsedTicks = 0;
    private Icon appIcon;

    public SplashForm(Process core)
    {
        this.childProc = core;
        this.FormBorderStyle = FormBorderStyle.None;
        this.StartPosition = FormStartPosition.CenterScreen;
        this.Size = new Size(440, 155);
        this.BackColor = Color.FromArgb(20, 24, 33);
        this.DoubleBuffered = true;
        this.TopMost = true;
        this.ShowInTaskbar = false;

        try
        {
            this.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            this.appIcon = this.Icon;
        }
        catch { }

        animTimer = new System.Windows.Forms.Timer();
        animTimer.Interval = 25;
        animTimer.Tick += (s, e) =>
        {
            barOffset = (barOffset + 12) % 440;
            this.Invalidate();
        };
        animTimer.Start();

        this.Shown += (s, e) =>
        {
            this.Refresh();
            StartPolling();
        };
    }

    // 核心程式在建立啟動畫面之前就先啟動，WinForms 準備畫面的時間和 Python 載入重疊
    public static Process StartCore(string[] args)
    {
        string appDir = AppDomain.CurrentDomain.BaseDirectory;
        string coreBin = Path.Combine(appDir, "WingLightPDF_Core.bin");
        if (!File.Exists(coreBin))
        {
            coreBin = Path.Combine(appDir, "FastPDF_Core.bin");
        }
        string coreExe = Path.Combine(appDir, "WingLightPDF_Core.exe");
        string mainPy = Path.Combine(appDir, "main.py");

        string quotedArgs = "";
        if (args != null && args.Length > 0)
        {
            for (int i = 0; i < args.Length; i++)
            {
                if (i > 0) quotedArgs += " ";
                quotedArgs += "\"" + args[i].Replace("\"", "\\\"") + "\"";
            }
        }

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.WorkingDirectory = appDir;
        psi.UseShellExecute = false;

        if (File.Exists(coreBin))
        {
            psi.FileName = coreBin;
            psi.Arguments = quotedArgs;
        }
        else if (File.Exists(coreExe))
        {
            psi.FileName = coreExe;
            psi.Arguments = quotedArgs;
        }
        else if (File.Exists(mainPy))
        {
            psi.FileName = "pythonw.exe";
            psi.Arguments = "\"" + mainPy + "\" " + quotedArgs;
        }
        else
        {
            MessageBox.Show("找不到核心程式檔案 (WingLightPDF_Core.bin 或 main.py)！", "WingLightPDF 啟動錯誤", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return null;
        }

        try
        {
            return Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("啟動失敗：" + ex.Message, "WingLightPDF", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return null;
        }
    }

    private void StartPolling()
    {
        pollTimer = new System.Windows.Forms.Timer();
        pollTimer.Interval = 50;
        pollTimer.Tick += (s, e) =>
        {
            elapsedTicks++;
            if (childProc == null || childProc.HasExited)
            {
                CloseSplash();
                return;
            }
            try
            {
                childProc.Refresh();
                if (childProc.MainWindowHandle != IntPtr.Zero || elapsedTicks > 90)
                {
                    CloseSplash();
                }
            }
            catch
            {
                CloseSplash();
            }
        };
        pollTimer.Start();
    }

    private void CloseSplash()
    {
        if (pollTimer != null) pollTimer.Stop();
        if (animTimer != null) animTimer.Stop();
        this.Close();
        Application.Exit();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;

        using (Pen borderPen = new Pen(Color.FromArgb(56, 189, 248), 2f))
        {
            g.DrawRectangle(borderPen, 1, 1, this.Width - 2, this.Height - 2);
        }

        int textLeft = 28;
        if (appIcon != null)
        {
            try
            {
                using (Bitmap bmp = appIcon.ToBitmap())
                {
                    g.DrawImage(bmp, new Rectangle(24, 26, 68, 68));
                    textLeft = 108;
                }
            }
            catch { }
        }

        using (Font titleFont = new Font("Microsoft JhengHei UI", 15f, FontStyle.Bold))
        using (Brush whiteBrush = new SolidBrush(Color.FromArgb(248, 250, 252)))
        {
            g.DrawString("WingLightPDF", titleFont, whiteBrush, textLeft, 24);
        }

        using (Font subFont = new Font("Microsoft JhengHei UI", 10.5f, FontStyle.Bold))
        using (Brush cyanBrush = new SolidBrush(Color.FromArgb(56, 189, 248)))
        {
            g.DrawString("輕快免安裝 PDF 檢視與編輯工具", subFont, cyanBrush, textLeft, 56);
        }

        using (Font hintFont = new Font("Microsoft JhengHei UI", 9f, FontStyle.Regular))
        using (Brush grayBrush = new SolidBrush(Color.FromArgb(148, 163, 184)))
        {
            g.DrawString("⚡ 正在極速載入引擎，請稍候...", hintFont, grayBrush, textLeft, 82);
        }

        Rectangle trackRect = new Rectangle(24, 118, this.Width - 48, 8);
        using (Brush trackBrush = new SolidBrush(Color.FromArgb(38, 44, 58)))
        {
            g.FillRectangle(trackBrush, trackRect);
        }

        g.SetClip(trackRect);
        int barWidth = 140;
        int bx = 24 + (barOffset % (trackRect.Width + barWidth)) - barWidth;
        Rectangle barRect = new Rectangle(bx, 118, barWidth, 8);
        using (LinearGradientBrush grad = new LinearGradientBrush(
            barRect,
            Color.FromArgb(239, 68, 68),
            Color.FromArgb(56, 189, 248),
            LinearGradientMode.Horizontal))
        {
            g.FillRectangle(grad, barRect);
        }
        g.ResetClip();
    }

    // ---- 單一執行個體：已經有 WingLightPDF 在執行時，把檔案交給它開在分頁（見 core/single_instance.py）----

    private const string MutexName = "Local\\WingLightPDF.Primary";

    [DllImport("user32.dll")]
    private static extern bool AllowSetForegroundWindow(int dwProcessId);

    private static string JsonString(string s)
    {
        StringBuilder sb = new StringBuilder("\"");
        foreach (char c in s)
        {
            if (c == '"') sb.Append("\\\"");
            else if (c == '\\') sb.Append("\\\\");
            else if (c < 0x20) sb.AppendFormat("\\u{0:x4}", (int)c);
            else sb.Append(c);
        }
        return sb.Append('"').ToString();
    }

    private static bool TrySendToRunningInstance(string[] args)
    {
        foreach (string a in args)
        {
            if (a.StartsWith("-")) return false;  // --self-test 等參數照舊啟動新的核心
        }
        try
        {
            using (Mutex.OpenExisting(MutexName)) { }
        }
        catch
        {
            return false;  // 沒有主程式在執行
        }
        try
        {
            AllowSetForegroundWindow(-1);  // 讓主程式可以把視窗帶到最前面
            StringBuilder json = new StringBuilder("{\"files\": [");
            for (int i = 0; i < args.Length; i++)
            {
                if (i > 0) json.Append(", ");
                json.Append(JsonString(Path.GetFullPath(args[i])));
            }
            json.Append("]}");
            byte[] data = Encoding.UTF8.GetBytes(json.ToString());

            string pipeName = "WingLightPDF-s" + Process.GetCurrentProcess().SessionId;
            using (NamedPipeClientStream pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut))
            {
                pipe.Connect(15000);  // 主程式可能剛啟動，還沒開始接收
                pipe.ReadMode = PipeTransmissionMode.Message;
                pipe.Write(data, 0, data.Length);
                pipe.Flush();
                byte[] ack = new byte[16];
                IAsyncResult r = pipe.BeginRead(ack, 0, ack.Length, null, null);
                if (!r.AsyncWaitHandle.WaitOne(5000)) return false;
                int n = pipe.EndRead(r);
                return n >= 2 && ack[0] == (byte)'O' && ack[1] == (byte)'K';
            }
        }
        catch
        {
            return false;  // 交不出去就照舊啟動一份新的
        }
    }

    [STAThread]
    public static void Main(string[] args)
    {
        if (TrySendToRunningInstance(args)) return;

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Process core = SplashForm.StartCore(args);
        if (core == null) return;
        Application.Run(new SplashForm(core));
    }
}
