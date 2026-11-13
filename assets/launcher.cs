using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

// 啟動畫面（WingLight 設計規範 Splash 元件）：420 × 320 的夜空，螢火蟲尾巴的光暈 2.2 秒一明一暗，
// 「啟動中」後面三個黃點每 1.2 秒輪流亮。C# 畫不出向量動畫，用亮、暗兩張 PNG 交替淡入淡出
// （assets\splash，由 tools\make_brand_assets.py 從規範的 firefly.svg 產生）。
// Windows 關掉動畫效果時，光暈和圓點都停在最亮。
public class SplashForm : Form
{
    private static readonly Color SplashBg = Color.FromArgb(0x15, 0x1A, 0x2E);
    private static readonly Color SplashText = Color.FromArgb(0xF2, 0xF0, 0xEC);
    private static readonly Color SplashMuted = Color.FromArgb(0xB0, 0xAB, 0xA3);
    private static readonly Color Glow = Color.FromArgb(0xFF, 0xC8, 0x3D);

    private System.Windows.Forms.Timer animTimer;
    private System.Windows.Forms.Timer pollTimer;
    private Process childProc;
    private int elapsedTicks = 0;
    private readonly Stopwatch clock = Stopwatch.StartNew();
    private double previewTime = -1;  // --splash-preview 用固定的時間點
    private readonly bool animate;
    private readonly float scale;
    private Image fireflyBright;
    private Image fireflyDim;

    [DllImport("user32.dll")]
    private static extern bool SystemParametersInfo(int uiAction, int uiParam, ref int pvParam, int fWinIni);

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

    public SplashForm(Process core)
    {
        this.childProc = core;
        this.FormBorderStyle = FormBorderStyle.None;
        this.StartPosition = FormStartPosition.CenterScreen;
        this.BackColor = SplashBg;
        this.DoubleBuffered = true;
        this.TopMost = true;
        this.ShowInTaskbar = false;
        this.Text = "WingLightPDF";

        using (Graphics g = Graphics.FromHwnd(IntPtr.Zero))
        {
            scale = g.DpiX / 96f;
        }
        this.ClientSize = new Size(S(420), S(320));

        int anim = 1;
        animate = !SystemParametersInfo(0x1042, 0, ref anim, 0) || anim != 0;  // SPI_GETCLIENTAREAANIMATION

        string dir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "assets", "splash");
        try
        {
            fireflyBright = Image.FromFile(Path.Combine(dir, "firefly_bright.png"));
            fireflyDim = Image.FromFile(Path.Combine(dir, "firefly_dim.png"));
        }
        catch
        {
            fireflyBright = null;  // 找不到圖：只顯示產品名與「啟動中」
            fireflyDim = null;
        }

        if (animate)
        {
            animTimer = new System.Windows.Forms.Timer();
            animTimer.Interval = 40;
            animTimer.Tick += (s, e) => this.Invalidate();
            animTimer.Start();
        }

        this.Shown += (s, e) =>
        {
            this.Refresh();
            StartPolling();
        };
    }

    private int S(float px)
    {
        return (int)Math.Round(px * scale);
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        int round = 2;  // Windows 11：DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
        bool rounded = false;
        try
        {
            rounded = DwmSetWindowAttribute(this.Handle, 33, ref round, sizeof(int)) == 0;
        }
        catch { }
        if (!rounded)
        {
            // Windows 10 沒有圓角設定，用 radius-xl（12px）的外框裁切
            int r = S(12) * 2;
            GraphicsPath path = new GraphicsPath();
            path.AddArc(0, 0, r, r, 180, 90);
            path.AddArc(this.Width - r, 0, r, r, 270, 90);
            path.AddArc(this.Width - r, this.Height - r, r, r, 0, 90);
            path.AddArc(0, this.Height - r, r, r, 90, 90);
            path.CloseFigure();
            this.Region = new Region(path);
        }
    }

    private double Now()
    {
        return previewTime >= 0 ? previewTime : clock.Elapsed.TotalSeconds;
    }

    // 尾巴光暈的亮度：0（暗）到 1（亮），2.2 秒一個週期
    private float GlowLevel()
    {
        if (!animate) return 1f;
        double t = Now();
        return (float)(0.5 - 0.5 * Math.Cos(2 * Math.PI * t / 2.2));
    }

    // 三個圓點裡現在亮的是第幾個（每個亮 0.4 秒）；不動畫時傳回 -1 表示全部亮
    private int ActiveDot()
    {
        if (!animate) return -1;
        return (int)((Now() % 1.2) / 0.4);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;

        int w = this.ClientSize.Width;
        Rectangle fly = new Rectangle((w - S(220)) / 2, S(14), S(220), S(220));
        if (fireflyDim != null && fireflyBright != null)
        {
            g.DrawImage(fireflyDim, fly);
            using (ImageAttributes ia = new ImageAttributes())
            {
                ColorMatrix cm = new ColorMatrix();
                cm.Matrix33 = GlowLevel();
                ia.SetColorMatrix(cm);
                g.DrawImage(fireflyBright, fly, 0, 0, fireflyBright.Width, fireflyBright.Height, GraphicsUnit.Pixel, ia);
            }
        }

        // splash-title：16px 粗體；splash-hint：12px（Microsoft JhengHei UI，pt 會跟著螢幕 DPI 換算）。
        // 用 TextRenderer（GDI）畫字：GDI+ 的 DrawString 找不到正黑體 UI 的粗體字面
        using (Font titleFont = new Font("Microsoft JhengHei UI", 12f, FontStyle.Bold))
        using (Font hintFont = new Font("Microsoft JhengHei UI", 9f, FontStyle.Regular))
        {
            TextFormatFlags flags = TextFormatFlags.NoPadding | TextFormatFlags.SingleLine;
            Size titleSize = TextRenderer.MeasureText(g, "WingLightPDF", titleFont, Size.Empty, flags);
            TextRenderer.DrawText(g, "WingLightPDF", titleFont, new Point((w - titleSize.Width) / 2, S(242)),
                                  SplashText, flags);

            const string hint = "啟動中";
            Size hintSize = TextRenderer.MeasureText(g, hint, hintFont, Size.Empty, flags);
            float dotsWidth = S(6) * 3 + S(4) * 2;
            int x = (int)((w - (hintSize.Width + S(6) + dotsWidth)) / 2f);
            int y = S(276);
            TextRenderer.DrawText(g, hint, hintFont, new Point(x, y), SplashMuted, flags);

            int active = ActiveDot();
            float dotY = y + hintSize.Height / 2f - S(3);
            float dotX = x + hintSize.Width + S(6);
            for (int i = 0; i < 3; i++)
            {
                int alpha = (active < 0 || active == i) ? 255 : 80;
                using (Brush dot = new SolidBrush(Color.FromArgb(alpha, Glow)))
                {
                    g.FillEllipse(dot, dotX + i * S(10), dotY, S(6), S(6));
                }
            }
        }
    }

    // 核心程式在建立啟動畫面之前就先啟動，WinForms 準備畫面的時間和 Python 載入重疊
    public static Process StartCore(string[] args)
    {
        string appDir = AppDomain.CurrentDomain.BaseDirectory;
        string coreBin = Path.Combine(appDir, "WingLightPDF_Core.bin");
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
            MessageBox.Show("找不到核心程式（WingLightPDF_Core.bin）。請確認整個資料夾都有解壓縮，不要只複製 WingLightPDF.exe。", "WingLightPDF 無法啟動", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return null;
        }

        try
        {
            return Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("無法啟動核心程式：" + ex.Message + "\n\n防毒軟體可能擋住了，可以把整個資料夾加入排除清單後再試一次。", "WingLightPDF 無法啟動", MessageBoxButtons.OK, MessageBoxIcon.Error);
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
                // 主視窗一出現就關；最多等 4.5 秒（規範 Splash）
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

    // 開發用：WingLightPDF.exe --splash-preview <資料夾>，把幾個動畫時間點的畫面存成 PNG 後結束，不啟動核心
    public static void SavePreview(string folder)
    {
        Directory.CreateDirectory(folder);
        using (SplashForm f = new SplashForm(null))
        {
            f.CreateControl();
            foreach (double t in new double[] { 0.0, 0.55, 1.1 })
            {
                f.previewTime = t;
                using (Bitmap bmp = new Bitmap(f.ClientSize.Width, f.ClientSize.Height))
                {
                    f.DrawToBitmap(bmp, new Rectangle(Point.Empty, f.ClientSize));
                    bmp.Save(Path.Combine(folder, string.Format("splash_{0:0.00}s.png", t)), ImageFormat.Png);
                }
            }
        }
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

    [DllImport("user32.dll")]
    private static extern bool SetProcessDPIAware();

    [STAThread]
    public static void Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--splash-preview")
        {
            SetProcessDPIAware();
            SavePreview(args[1]);
            return;
        }
        if (TrySendToRunningInstance(args)) return;

        SetProcessDPIAware();  // 高解析度螢幕上不要被 Windows 放大成模糊的點陣圖
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Process core = SplashForm.StartCore(args);
        if (core == null) return;
        Application.Run(new SplashForm(core));
    }
}
