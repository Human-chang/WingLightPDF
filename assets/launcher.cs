using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Windows.Forms;

public class SplashForm : Form
{
    private Timer animTimer;
    private Timer pollTimer;
    private Process childProc;
    private int barOffset = 0;
    private int elapsedTicks = 0;
    private Icon appIcon;

    public SplashForm(string[] args)
    {
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

        animTimer = new Timer();
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
            StartBackend(args);
        };
    }

    private void StartBackend(string[] args)
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
            Application.Exit();
            return;
        }

        try
        {
            childProc = Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("啟動失敗：" + ex.Message, "WingLightPDF", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Application.Exit();
            return;
        }

        pollTimer = new Timer();
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

    [STAThread]
    public static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new SplashForm(args));
    }
}
