using System;
using System.Drawing;
using System.Windows.Forms;
using System.Net.Sockets;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using ARC;

namespace Memory
{
    public partial class MainForm : ARC.UCForms.FormPluginMaster
    {

        Configuration _config;
        ARC.UCForms.FormCameraDevice _cameraControl;
        Bitmap _latestFrame;
        System.Timers.Timer _saveTimer;
        System.Timers.Timer _readTimer;
        bool _saving = false;

        // ---------- socket ----------
        const string MEMORY_HOST = "127.0.0.1";
        const int MEMORY_PORT = 5005;
        TcpClient _sock;
        // Where Python and this plugin swap files. Asked from the
        // Python side on connect; this is only the fallback for when
        // the brain isn't up yet.
        string _bridgeDir = @"D:\face_bridge";
        StreamReader _sockReader;
        StreamWriter _sockWriter;
        readonly object _sockLock = new object();
        System.Timers.Timer _statusTimer;
        System.Timers.Timer _connectTimer;

        // ---------- theme ----------
        static readonly Color BG_PANEL = Color.FromArgb(37, 47, 62);
        static readonly Color BG_CARD = Color.FromArgb(48, 60, 78);
        static readonly Color BG_BTN = Color.FromArgb(62, 78, 100);
        static readonly Color BG_CHIP = Color.FromArgb(30, 68, 96);
        static readonly Color BG_MIC = Color.FromArgb(0, 140, 190);
        static readonly Color TXT = Color.Gainsboro;
        static readonly Color TXT_DIM = Color.FromArgb(150, 165, 185);
        static readonly Color TXT_CHIP = Color.FromArgb(120, 200, 240);
        static readonly Color OK_GREEN = Color.FromArgb(70, 190, 120);
        static readonly Color OFF_RED = Color.FromArgb(200, 85, 85);
        const int W = 330;

        // ---------- controls ----------
        Label _dot, _lblConn;
        Label _valPerson, _valObject, _valEvent;
        TextBox _txtQuestion, _txtAnswer;
        Button _btnMic, _btnGesture;
        Label _lblLegend;
        bool _gestureOn = false;

        static readonly string[] EXAMPLES = {
            "Who did you see?",
            "What did person pick up?",
            "What happened?",
            "Wave at me",
        };

        // Spelled out fully so a first-time user knows which finger and
        // direction, not just "point - turn".
        const string LEGEND =
            "Fist  -  walk forward\n" +
            "Open hand  -  stop\n" +
            "Index finger pointing left  -  turn left\n" +
            "Index finger pointing right  -  turn right\n" +
            "Index finger pointing down  -  sit down\n" +
            "Two fingers up (peace sign)  -  wave\n" +
            "Three fingers up  -  stand up\n" +
            "Index finger + little finger  -  push-ups";

        public MainForm()
        {

            InitializeComponent();
            ConfigButton = true;

            // Remove the template's default welcome label (it fills the form).
            this.Controls.Clear();
            this.BackColor = BG_PANEL;

            FlowLayoutPanel root = new FlowLayoutPanel();
            root.Dock = DockStyle.Fill;
            root.FlowDirection = FlowDirection.LeftToRight;
            root.WrapContents = false;
            root.AutoScroll = true;
            root.BackColor = BG_PANEL;
            root.Padding = new Padding(10);
            this.Controls.Add(root);
            root.BringToFront();

            // Two side-by-side columns, so the whole panel fits on screen
            // without scrolling: seeing + asking on the left, doing on the
            // right.
            FlowLayoutPanel colLeft = Col(root);
            FlowLayoutPanel colRight = Col(root);

            // ---------- header ----------
            FlowLayoutPanel head = Row(colLeft, 26);
            Label title = Mk<Label>(head, 176, 20);
            title.Text = "JD 2.0";
            title.Font = new Font("Segoe UI", 10F, FontStyle.Bold);

            _dot = new Label();
            _dot.Size = new Size(10, 10);
            _dot.BackColor = OFF_RED;
            _dot.Margin = new Padding(6, 6, 6, 0);
            head.Controls.Add(_dot);

            _lblConn = Mk<Label>(head, 110, 20);
            _lblConn.Text = "starting...";
            _lblConn.ForeColor = TXT_DIM;
            _lblConn.Font = new Font("Segoe UI", 8.5F);

            // ---------- what JD sees ----------
            Header(colLeft, "What JD sees right now");
            Panel card = new Panel();
            card.Size = new Size(W, 74);
            card.BackColor = BG_CARD;
            card.Margin = new Padding(0, 0, 0, 6);
            colLeft.Controls.Add(card);

            Field(card, "Person", 6, out _valPerson);
            Field(card, "Holding", 28, out _valObject);
            Field(card, "Last event", 50, out _valEvent);

            // ---------- ask ----------
            // One box for everything. The Python side routes it:
            // questions about the past go to the witness diary,
            // anything else ("wave", "hello") goes to the
            // command-and-act system.
            Header(colLeft, "Ask JD, or tell it what to do");

            FlowLayoutPanel chips = new FlowLayoutPanel();
            chips.Size = new Size(W, 64);
            chips.FlowDirection = FlowDirection.LeftToRight;
            chips.WrapContents = true;
            chips.Margin = new Padding(0, 0, 0, 6);
            chips.BackColor = Color.Transparent;
            colLeft.Controls.Add(chips);

            foreach (string ex in EXAMPLES)
            {
                string q = ex;                       // capture per iteration
                Button chip = new Button();
                chip.Text = q;
                chip.AutoSize = false;
                chip.Size = new Size(TextRenderer.MeasureText(q,
                                new Font("Segoe UI", 8.5F)).Width + 18, 26);
                chip.BackColor = BG_CHIP;
                chip.ForeColor = TXT_CHIP;
                chip.FlatStyle = FlatStyle.Flat;
                chip.FlatAppearance.BorderSize = 0;
                chip.Font = new Font("Segoe UI", 8.5F);
                chip.Margin = new Padding(0, 0, 4, 4);
                chip.Cursor = Cursors.Hand;
                chip.Click += (s, e) => AskThis(q);
                chips.Controls.Add(chip);
            }

            FlowLayoutPanel askRow = Row(colLeft, 32);
            _txtQuestion = new TextBox();
            _txtQuestion.Size = new Size(W - 62, 24);
            _txtQuestion.BackColor = BG_CARD;
            _txtQuestion.ForeColor = TXT;
            _txtQuestion.BorderStyle = BorderStyle.FixedSingle;
            _txtQuestion.Font = new Font("Segoe UI", 9F);
            _txtQuestion.Margin = new Padding(0, 2, 4, 0);
            _txtQuestion.KeyDown += (s, e) =>
            {
                if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; MemoryAsk(); }
            };
            askRow.Controls.Add(_txtQuestion);

            Button btnAsk = Btn(askRow, "Ask", 52, 26);
            btnAsk.Click += (s, e) => MemoryAsk();

            // ---------- hold to talk ----------
            _btnMic = Btn(colLeft, "Hold to speak", W, 38);
            _btnMic.BackColor = BG_MIC;
            _btnMic.Font = new Font("Segoe UI", 10F, FontStyle.Bold);
            _btnMic.Cursor = Cursors.Hand;
            // MouseDown/MouseUp, not Click - held while speaking, released
            // when done, so there's no need to detect end-of-speech.
            _btnMic.MouseDown += (s, e) => MicDown();
            _btnMic.MouseUp += (s, e) => MicUp();

            _txtAnswer = new TextBox();
            _txtAnswer.Size = new Size(W, 62);
            _txtAnswer.Multiline = true;
            _txtAnswer.ReadOnly = true;
            _txtAnswer.ScrollBars = ScrollBars.Vertical;
            _txtAnswer.BackColor = BG_CARD;
            _txtAnswer.ForeColor = TXT;
            _txtAnswer.BorderStyle = BorderStyle.FixedSingle;
            _txtAnswer.Font = new Font("Segoe UI", 9F);
            _txtAnswer.Margin = new Padding(0, 0, 0, 6);
            colLeft.Controls.Add(_txtAnswer);

            // ---------- gestures ----------
            Header(colRight, "Hand gesture control");
            _btnGesture = Btn(colRight, "Turn on hand control", W, 32);
            _btnGesture.Click += (s, e) => SetGesture(!_gestureOn);

            _lblLegend = Mk<Label>(colRight, W, 118);
            _lblLegend.Text = LEGEND;
            _lblLegend.ForeColor = TXT_DIM;
            _lblLegend.Font = new Font("Segoe UI", 8F);
            _lblLegend.Margin = new Padding(4, 2, 0, 8);

            // ---------- setup ----------
            Header(colRight, "Setup");
            Button btnAttach = Btn(colRight, "Attach to JD's camera", W, 26);
            btnAttach.Font = new Font("Segoe UI", 8F);
            btnAttach.Click += (s, e) => attach();

            Button btnStop = Btn(colRight, "Stop the vision loop", W, 26);
            btnStop.Font = new Font("Segoe UI", 8F);
            btnStop.ForeColor = OFF_RED;
            btnStop.Click += (s, e) => ConfirmStop();

            // ---------- timers ----------
            _statusTimer = new System.Timers.Timer();
            _statusTimer.Interval = 1000;
            _statusTimer.Elapsed += StatusTimer_Elapsed;

            // Keep retrying the connection - Python may not be up yet when
            // ARC loads the panel. Goes green once it connects.
            _connectTimer = new System.Timers.Timer();
            _connectTimer.Interval = 2000;
            _connectTimer.Elapsed += (s, e) =>
            {
                if (_sock == null || !_sock.Connected) MemoryConnect(true);
            };
            _connectTimer.Start();

            _saveTimer = new System.Timers.Timer();
            _saveTimer.Interval = 500;
            _saveTimer.Elapsed += SaveTimer_Elapsed;

            _readTimer = new System.Timers.Timer();
            _readTimer.Interval = 500;
            _readTimer.Elapsed += ReadTimer_Elapsed;

            PaintGesture();
        }

        // ---------- tiny UI builders ----------
        T Mk<T>(Control parent, int w, int h) where T : Control, new()
        {
            T c = new T();
            c.Size = new Size(w, h);
            c.ForeColor = TXT;
            c.Font = new Font("Segoe UI", 9F);
            c.Margin = new Padding(0, 0, 0, 4);
            parent.Controls.Add(c);
            return c;
        }

        FlowLayoutPanel Col(Control parent)
        {
            FlowLayoutPanel c = new FlowLayoutPanel();
            c.FlowDirection = FlowDirection.TopDown;
            c.WrapContents = false;
            c.AutoSize = true;
            c.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            c.BackColor = Color.Transparent;
            c.Margin = new Padding(0, 0, 14, 0);
            parent.Controls.Add(c);
            return c;
        }

        FlowLayoutPanel Row(Control parent, int h)
        {
            FlowLayoutPanel r = new FlowLayoutPanel();
            r.Size = new Size(W, h);
            r.FlowDirection = FlowDirection.LeftToRight;
            r.WrapContents = false;
            r.Margin = new Padding(0, 0, 0, 4);
            r.BackColor = Color.Transparent;
            parent.Controls.Add(r);
            return r;
        }

        void Header(Control parent, string text)
        {
            Label l = Mk<Label>(parent, W, 17);
            l.Text = text;
            l.ForeColor = TXT_DIM;
            l.Font = new Font("Segoe UI", 8F, FontStyle.Bold);
            l.Margin = new Padding(0, 8, 0, 2);
        }

        Button Btn(Control parent, string text, int w, int h)
        {
            Button b = new Button();
            b.Text = text;
            b.Size = new Size(w, h);
            b.BackColor = BG_BTN;
            b.ForeColor = TXT;
            b.FlatStyle = FlatStyle.Flat;
            b.FlatAppearance.BorderSize = 0;
            b.Font = new Font("Segoe UI", 9F);
            b.Margin = new Padding(0, 0, 4, 4);
            parent.Controls.Add(b);
            return b;
        }

        void Field(Control card, string name, int y, out Label val)
        {
            Label k = new Label();
            k.Text = name;
            k.Location = new Point(8, y);
            k.Size = new Size(58, 17);
            k.ForeColor = TXT_DIM;
            k.Font = new Font("Segoe UI", 8F);
            card.Controls.Add(k);

            val = new Label();
            val.Text = "-";
            val.Location = new Point(70, y);
            val.Size = new Size(W - 80, 17);
            val.ForeColor = TXT;
            val.Font = new Font("Segoe UI", 9F, FontStyle.Bold);
            val.AutoEllipsis = true;
            card.Controls.Add(val);
        }

        void PaintGesture()
        {
            _btnGesture.BackColor = _gestureOn ? BG_MIC : BG_BTN;
            _btnGesture.Text = _gestureOn ? "Turn off hand control"
                                          : "Turn on hand control";
        }

        // ---------- socket ----------
        void MemoryConnect(bool quiet)
        {
            lock (_sockLock)
            {
                try
                {
                    MemoryCloseSocket();
                    _sock = new TcpClient();
                    _sock.Connect(MEMORY_HOST, MEMORY_PORT);
                    NetworkStream ns = _sock.GetStream();
                    _sockReader = new StreamReader(ns, Encoding.UTF8);
                    _sockWriter = new StreamWriter(ns, new UTF8Encoding(false));
                    _sockWriter.AutoFlush = true;
                    ARC.EZBManager.Log("MEMORY: connected.");
                }
                catch (Exception)
                {
                    // Python not up yet; the timer will retry quietly.
                    SetConn(false, "waiting for JD's brain...");
                    return;
                }
            }
            SetConn(true, "Ready");
            string dir = MemorySend("bridgedir");
            if (dir != null && dir.StartsWith("OK: "))
                _bridgeDir = dir.Substring(4).Trim();
            _statusTimer.Start();
        }

        void MemoryCloseSocket()
        {
            try { if (_sockReader != null) _sockReader.Dispose(); } catch { }
            try { if (_sockWriter != null) _sockWriter.Dispose(); } catch { }
            try { if (_sock != null) _sock.Close(); } catch { }
            _sock = null; _sockReader = null; _sockWriter = null;
        }

        string MemorySend(string cmd)
        {
            lock (_sockLock)
            {
                if (_sock == null || !_sock.Connected) return null;
                try
                {
                    _sockWriter.Write(cmd + "\n");
                    _sockWriter.Flush();
                    return _sockReader.ReadLine();
                }
                catch (Exception ex)
                {
                    ARC.EZBManager.Log("MEMORY send error: " + ex.Message);
                    return null;
                }
            }
        }

        // ---------- actions ----------
        void AskThis(string text)
        {
            SetAnswer("Thinking...");
            Task.Run(() =>
            {
                string reply = MemorySend(text);
                if (reply == null) reply = "JD's brain isn't running yet.";
                if (reply.StartsWith("OK: ")) reply = reply.Substring(4);
                SetAnswer(reply);
            });
        }

        void MemoryAsk()
        {
            string q = _txtQuestion.Text.Trim();
            if (q == "") return;
            AskThis(q);
        }

        void MicDown()
        {
            if (_sock == null || !_sock.Connected)
            {
                SetAnswer("JD's brain isn't running yet.");
                return;
            }
            UI(() => _btnMic.Text = "Listening... let go when done");
            SetAnswer("Listening...");
            Task.Run(() => MemorySend("listen start"));
        }

        void MicUp()
        {
            UI(() => _btnMic.Text = "Thinking...");
            Task.Run(() =>
            {
                string reply = MemorySend("listen stop");
                if (reply == null) reply = "JD's brain isn't running yet.";
                if (reply.StartsWith("OK: ")) reply = reply.Substring(4);
                SetAnswer(reply);
                UI(() => _btnMic.Text = "Hold to speak");
            });
        }

        void SetGesture(bool on)
        {
            Task.Run(() =>
            {
                string reply = MemorySend(on ? "gesture on" : "gesture off");
                if (reply == null || reply.StartsWith("ERR") || reply.StartsWith("UNKNOWN"))
                {
                    SetAnswer("Hand control isn't available right now.");
                    return;
                }
                _gestureOn = on;
                UI(() => PaintGesture());
            });
        }

        // A judge WILL click this out of curiosity. Make them mean it - one
        // stray click otherwise leaves JD brain-dead mid-demo, and the only
        // way back is a terminal.
        void ConfirmStop()
        {
            if (MessageBox.Show("This shuts down JD's brain. Everything on this "
                                + "panel stops working until it's restarted from "
                                + "the computer.\n\nAre you sure?",
                                "Stop the vision loop?",
                                MessageBoxButtons.YesNo,
                                MessageBoxIcon.Warning) == DialogResult.Yes)
            {
                MemorySend("stop");
            }
        }

        void StatusTimer_Elapsed(object sender, System.Timers.ElapsedEventArgs e)
        {
            string reply = MemorySend("status");
            if (reply == null)
            {
                _statusTimer.Stop();
                SetConn(false, "waiting for JD's brain...");
                return;
            }
            if (reply.StartsWith("STATUS ")) reply = reply.Substring(7);
            ApplyStatus(reply);
        }

        // "person=X | object=Y | event=Z | gesture=on"
        void ApplyStatus(string s)
        {
            string person = "-", obj = "-", evt = "-", gest = "off";
            foreach (string part in s.Split('|'))
            {
                string t = part.Trim();
                int eq = t.IndexOf('=');
                if (eq < 0) continue;
                string k = t.Substring(0, eq).Trim().ToLower();
                string v = t.Substring(eq + 1).Trim();
                if (k == "person") person = v;
                else if (k == "object") obj = v;
                else if (k == "event") evt = v;
                else if (k == "gesture") gest = v;
            }
            bool g = (gest == "on");
            string p = person, o = obj, ev = evt;
            UI(() =>
            {
                _valPerson.Text = (p == "-") ? "nobody" : p;
                _valObject.Text = (o == "-") ? "nothing" : o;
                _valEvent.Text = ev;
                if (g != _gestureOn) { _gestureOn = g; PaintGesture(); }
            });
        }

        void SetConn(bool ok, string text)
        {
            UI(() =>
            {
                _dot.BackColor = ok ? OK_GREEN : OFF_RED;
                _lblConn.Text = text;
                _lblConn.ForeColor = ok ? OK_GREEN : TXT_DIM;
                if (!ok)
                {
                    _valPerson.Text = "-";
                    _valObject.Text = "-";
                    _valEvent.Text = "-";
                }
            });
        }

        void SetAnswer(string text)
        {
            UI(() => _txtAnswer.Text = text);
        }

        void UI(Action a)
        {
            if (this.InvokeRequired) this.BeginInvoke(a);
            else a();
        }

        // ---------- camera bridge (unchanged) ----------
        void attach()
        {

            detach();

            Control[] cameras = ARC.EZBManager.FormMain.GetControlByType(typeof(ARC.UCForms.FormCameraDevice));

            if (cameras.Length == 0)
            {
                MessageBox.Show("There are no camera controls in this project. Add a Camera Device first.");
                return;
            }

            _cameraControl = (ARC.UCForms.FormCameraDevice)cameras[0];
            _cameraControl.Camera.OnNewFrame += Camera_OnNewFrame;
            _saveTimer.Start();
            _readTimer.Start();
            ARC.EZBManager.Log("Attached to camera: {0}", _cameraControl.Text);
        }

        void detach()
        {

            _saveTimer.Stop();
            _readTimer.Stop();
            if (_cameraControl != null)
            {
                _cameraControl.Camera.OnNewFrame -= Camera_OnNewFrame;
                _cameraControl = null;
            }
        }

        void Camera_OnNewFrame()
        {
            if (_cameraControl == null) return;
            _latestFrame = _cameraControl.Camera.GetCurrentBitmapManaged;
        }

        void SaveTimer_Elapsed(object sender, System.Timers.ElapsedEventArgs e)
        {

            if (_saving) return;
            if (_latestFrame == null) return;

            _saving = true;
            try
            {
                // Write to a temp file, then swap it into place. The swap
                // is instant, so Python can never read half a frame - the
                // same atomic pattern every file in this project uses.
                System.IO.Directory.CreateDirectory(_bridgeDir);
                string dest = System.IO.Path.Combine(_bridgeDir, "frame.jpg");
                string tmp = dest + ".tmp";
                Bitmap copy = new Bitmap(_latestFrame);
                copy.Save(tmp, System.Drawing.Imaging.ImageFormat.Jpeg);
                copy.Dispose();
                if (System.IO.File.Exists(dest))
                    System.IO.File.Replace(tmp, dest, null);
                else
                    System.IO.File.Move(tmp, dest);
            }
            catch (Exception ex)
            {
                ARC.EZBManager.Log("Save error: " + ex.Message);
            }
            finally
            {
                _saving = false;
            }
        }

        void ReadTimer_Elapsed(object sender, System.Timers.ElapsedEventArgs e)
        {
            try
            {
                string namePath = System.IO.Path.Combine(_bridgeDir, "name.txt");
                if (System.IO.File.Exists(namePath))
                {
                    string name = System.IO.File.ReadAllText(namePath).Trim();
                    ARC.Scripting.VariableManager.SetVariable("$FaceName", name);
                }
                string holdingPath = System.IO.Path.Combine(_bridgeDir, "holding.txt");
                if (System.IO.File.Exists(holdingPath))
                {
                    string holding = System.IO.File.ReadAllText(holdingPath).Trim();
                    ARC.Scripting.VariableManager.SetVariable("$Holding", holding);
                }
            }
            catch (Exception ex)
            {
                ARC.EZBManager.Log("Read error: " + ex.Message);
            }
        }

        private void MainForm_FormClosing(object sender, FormClosingEventArgs e)
        {
            detach();
            if (_statusTimer != null) _statusTimer.Stop();
            if (_connectTimer != null) _connectTimer.Stop();
            MemoryCloseSocket();
        }

        // --- config plumbing (unchanged) ---
        public override void SetConfiguration(ARC.Config.Sub.PluginV1 cf)
        {
            _config = (Configuration)cf.GetCustomObjectV2(typeof(Configuration));
            base.SetConfiguration(cf);
        }
        public override ARC.Config.Sub.PluginV1 GetConfiguration()
        {
            _cf.SetCustomObjectV2(_config);
            return base.GetConfiguration();
        }
        public override void ConfigPressed()
        {
            using (var form = new ConfigForm())
            {
                form.SetConfiguration(_config);
                if (form.ShowDialog() != DialogResult.OK) return;
                _config = form.GetConfiguration();
            }
        }
    }
}