using System;
using System.Collections.Generic;
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

        // ---------- socket ----------
        const string MEMORY_HOST = "127.0.0.1";
        const int MEMORY_PORT = 5005;
        TcpClient _sock;
        StreamReader _sockReader;
        StreamWriter _sockWriter;
        readonly object _sockLock = new object();
        System.Timers.Timer _statusTimer;
        System.Timers.Timer _connectTimer;
        int _tick = 0;                    // diary refreshes every 2nd status poll
        string _lastDiaryBlob = null;     // skip repainting an unchanged list

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
        Label _dot, _lblConn, _lblQuota;
        Label _valPerson, _valObject, _valEvent;
        TextBox _txtQuestion, _txtLog;
        Button _btnMic, _btnGesture;
        Label _lblLegend;
        ListBox _lstDiary, _lstAlerts;
        Label _lblAlertCount;
        string _lastAlertBlob = null;
        bool _gestureOn = false;
        string _personName = "-";

        // "{person}" is filled in live from whoever the camera currently
        // sees, so the panel visibly knows who it is looking at.
        readonly string[] EXAMPLES = {
            "Who did you see?",
            "What did {person} pick up?",
            "What happened?",
            "Wave at me",
        };
        readonly List<KeyValuePair<Button, string>> _chips =
            new List<KeyValuePair<Button, string>>();

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

            // Two side-by-side columns: seeing + talking on the left,
            // gestures + the live diary on the right.
            FlowLayoutPanel colLeft = Col(root);
            FlowLayoutPanel colRight = Col(root);

            // ---------- header: name, connection, API budget ----------
            Label title = Mk<Label>(colLeft, W, 20);
            title.Text = "JD Cortex  -  Witness Memory";
            title.Font = new Font("Segoe UI", 10F, FontStyle.Bold);

            FlowLayoutPanel head = Row(colLeft, 18);
            _dot = new Label();
            _dot.Size = new Size(10, 10);
            _dot.BackColor = OFF_RED;
            _dot.Margin = new Padding(0, 4, 6, 0);
            head.Controls.Add(_dot);

            _lblConn = Mk<Label>(head, 158, 16);
            _lblConn.Text = "starting...";
            _lblConn.ForeColor = TXT_DIM;
            _lblConn.Font = new Font("Segoe UI", 8.5F);

            _lblQuota = Mk<Label>(head, 150, 16);
            _lblQuota.Text = "";
            _lblQuota.ForeColor = TXT_DIM;
            _lblQuota.Font = new Font("Segoe UI", 8.5F);
            _lblQuota.TextAlign = ContentAlignment.TopRight;

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

            FlowLayoutPanel chipRow = new FlowLayoutPanel();
            chipRow.Size = new Size(W, 64);
            chipRow.FlowDirection = FlowDirection.LeftToRight;
            chipRow.WrapContents = true;
            chipRow.Margin = new Padding(0, 0, 0, 6);
            chipRow.BackColor = Color.Transparent;
            colLeft.Controls.Add(chipRow);

            foreach (string template in EXAMPLES)
            {
                Button chip = new Button();
                chip.AutoSize = true;
                chip.AutoSizeMode = AutoSizeMode.GrowAndShrink;
                chip.Padding = new Padding(4, 1, 4, 1);
                chip.BackColor = BG_CHIP;
                chip.ForeColor = TXT_CHIP;
                chip.FlatStyle = FlatStyle.Flat;
                chip.FlatAppearance.BorderSize = 0;
                chip.Font = new Font("Segoe UI", 8.5F);
                chip.Margin = new Padding(0, 0, 4, 4);
                chip.Cursor = Cursors.Hand;
                chip.Text = FillPerson(template);
                chip.Click += (s, e) => AskThis(((Button)s).Text);
                chipRow.Controls.Add(chip);
                _chips.Add(new KeyValuePair<Button, string>(chip, template));
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

            // Conversation log, not a single-answer box: during a demo the
            // history of what was asked and answered IS the story.
            _txtLog = new TextBox();
            _txtLog.Size = new Size(W, 96);
            _txtLog.Multiline = true;
            _txtLog.ReadOnly = true;
            _txtLog.ScrollBars = ScrollBars.Vertical;
            _txtLog.BackColor = BG_CARD;
            _txtLog.ForeColor = TXT;
            _txtLog.BorderStyle = BorderStyle.FixedSingle;
            _txtLog.Font = new Font("Segoe UI", 8.5F);
            _txtLog.Margin = new Padding(0, 0, 0, 6);
            colLeft.Controls.Add(_txtLog);

            // ---------- gestures ----------
            Header(colRight, "Hand gesture control");
            _btnGesture = Btn(colRight, "Turn on hand control", W, 32);
            _btnGesture.Click += (s, e) => SetGesture(!_gestureOn);

            _lblLegend = Mk<Label>(colRight, W, 118);
            _lblLegend.Text = LEGEND;
            _lblLegend.ForeColor = TXT_DIM;
            _lblLegend.Font = new Font("Segoe UI", 8F);
            _lblLegend.Margin = new Padding(4, 2, 0, 8);

            // ---------- surveillance ----------
            // Deliberately "entries", not "people": the watcher keys off
            // tracker ids and those get reassigned, so one visitor can
            // produce several lines. Overstating this as a person count
            // would be the panel lying.
            FlowLayoutPanel alertHead = Row(colRight, 18);
            Label alertTitle = Mk<Label>(alertHead, 210, 16);
            alertTitle.Text = "Security log";
            alertTitle.ForeColor = TXT_DIM;
            alertTitle.Font = new Font("Segoe UI", 8F, FontStyle.Bold);
            alertHead.Margin = new Padding(0, 8, 0, 2);

            _lblAlertCount = Mk<Label>(alertHead, 118, 16);
            _lblAlertCount.Text = "";
            _lblAlertCount.ForeColor = TXT_DIM;
            _lblAlertCount.Font = new Font("Segoe UI", 8F);
            _lblAlertCount.TextAlign = ContentAlignment.TopRight;

            _lstAlerts = new ListBox();
            _lstAlerts.Size = new Size(W, 64);
            _lstAlerts.BackColor = BG_CARD;
            _lstAlerts.ForeColor = TXT;
            _lstAlerts.BorderStyle = BorderStyle.FixedSingle;
            _lstAlerts.Font = new Font("Consolas", 8.25F);
            _lstAlerts.IntegralHeight = false;
            _lstAlerts.SelectionMode = SelectionMode.None;
            _lstAlerts.Margin = new Padding(0, 0, 0, 4);
            _lstAlerts.Items.Add("(waiting for JD's brain)");
            // Sensitive-object alerts are the ones worth spotting across
            // a room, so they draw in red while routine sightings stay
            // plain.
            _lstAlerts.DrawMode = DrawMode.OwnerDrawFixed;
            _lstAlerts.DrawItem += Alerts_DrawItem;
            colRight.Controls.Add(_lstAlerts);

            // ---------- the diary, live ----------
            // This is the project: watching JD's memory fill in while
            // someone walks past is the most demonstrable thing it does.
            Header(colRight, "JD's memory today (live)");
            _lstDiary = new ListBox();
            _lstDiary.Size = new Size(W, 120);
            _lstDiary.BackColor = BG_CARD;
            _lstDiary.ForeColor = TXT;
            _lstDiary.BorderStyle = BorderStyle.FixedSingle;
            _lstDiary.Font = new Font("Consolas", 8.25F);
            _lstDiary.IntegralHeight = false;
            _lstDiary.SelectionMode = SelectionMode.None;
            _lstDiary.Margin = new Padding(0, 0, 0, 8);
            _lstDiary.Items.Add("(waiting for JD's brain)");
            colRight.Controls.Add(_lstDiary);

            // A judge WILL click any button out of curiosity, so the one
            // destructive action is small, labeled for what it really
            // does, and confirms first.
            Button btnStop = Btn(colRight, "Shut down JD's brain", W, 24);
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

        string FillPerson(string template)
        {
            string name = _personName;
            if (name == "-" || name == "") name = "the last person";
            else if (name.Contains(",")) name = name.Split(',')[0].Trim();
            return template.Replace("{person}", name);
        }

        void PaintGesture()
        {
            _btnGesture.BackColor = _gestureOn ? BG_MIC : BG_BTN;
            _btnGesture.Text = _gestureOn ? "Hand control ON  -  open hand stops"
                                          : "Turn on hand control";
            // The legend lights up only while gestures actually do
            // something, so it never suggests they work when off.
            _lblLegend.ForeColor = _gestureOn ? TXT : TXT_DIM;
        }

        // Timestamped running log; the old single-answer box forgot each
        // exchange as soon as the next one started.
        void Log(string who, string text)
        {
            if (text == null || text.Trim() == "") return;
            string line = DateTime.Now.ToString("HH:mm") + "  " + who + ": "
                          + text.Trim();
            UI(() =>
            {
                _txtLog.AppendText(line + "\r\n");
                if (_txtLog.Lines.Length > 60)
                {
                    string[] lines = _txtLog.Lines;
                    string[] keep = new string[40];
                    Array.Copy(lines, lines.Length - 40, keep, 0, 40);
                    _txtLog.Text = string.Join("\r\n", keep) + "\r\n";
                }
                _txtLog.SelectionStart = _txtLog.Text.Length;
                _txtLog.ScrollToCaret();
            });
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
            _lastDiaryBlob = null;        // force a fresh paint of both lists
            _lastAlertBlob = null;
            RefreshDiary();
            RefreshAlerts();
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
            Log("You", text);
            Task.Run(() =>
            {
                string reply = MemorySend(text);
                if (reply == null) reply = "JD's brain isn't running yet.";
                if (reply.StartsWith("OK: ")) reply = reply.Substring(4);
                Log("JD", reply);
            });
        }

        void MemoryAsk()
        {
            string q = _txtQuestion.Text.Trim();
            if (q == "") return;
            UI(() => _txtQuestion.Text = "");
            AskThis(q);
        }

        void MicDown()
        {
            if (_sock == null || !_sock.Connected)
            {
                Log("panel", "JD's brain isn't running yet.");
                return;
            }
            UI(() => _btnMic.Text = "Listening... let go when done");
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

                // The Python side answers:  "<heard>"  ->  <reply>
                // Split it so the log shows what JD heard before what it
                // said - if the transcript is wrong, the answer will be
                // too, and this makes that visible.
                int arrow = reply.IndexOf("\"  ->  ");
                if (reply.StartsWith("\"") && arrow > 0)
                {
                    Log("You (voice)", reply.Substring(1, arrow - 1));
                    Log("JD", reply.Substring(arrow + 7));
                }
                else
                {
                    Log("JD", reply);
                }
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
                    Log("panel", reply == null
                        ? "Hand control isn't available right now."
                        : reply);
                    return;
                }
                _gestureOn = on;
                UI(() => PaintGesture());
            });
        }

        // One stray click otherwise leaves JD brain-dead mid-demo, and the
        // only way back is a terminal.
        void ConfirmStop()
        {
            if (MessageBox.Show("This shuts down JD's brain. Everything on this "
                                + "panel stops working until it's restarted from "
                                + "the computer.\n\nAre you sure?",
                                "Shut down JD's brain?",
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

            // The diary changes on a human timescale; every other poll is
            // plenty and keeps this timer's work small.
            if ((++_tick & 1) == 0) { RefreshDiary(); RefreshAlerts(); }
        }

        // "person=X | object=Y | event=Z | gesture=on | gemini 4/5 ok"
        // Segments without '=' are extras like the API counter.
        void ApplyStatus(string s)
        {
            string person = "-", obj = "-", evt = "-", gest = "off";
            string quota = null;
            foreach (string part in s.Split('|'))
            {
                string t = part.Trim();
                int eq = t.IndexOf('=');
                if (eq < 0)
                {
                    if (t.StartsWith("gemini")) quota = t;
                    continue;
                }
                string k = t.Substring(0, eq).Trim().ToLower();
                string v = t.Substring(eq + 1).Trim();
                if (k == "person") person = v;
                else if (k == "object") obj = v;
                else if (k == "event") evt = v;
                else if (k == "gesture") gest = v;
            }
            bool g = (gest == "on");
            string p = person, o = obj, ev = evt, qu = quota;
            UI(() =>
            {
                _valPerson.Text = (p == "-") ? "nobody" : p;
                _valObject.Text = (o == "-") ? "nothing" : o;
                _valEvent.Text = ev;
                if (qu != null)
                {
                    _lblQuota.Text = qu;
                    // Anything but zero quota hits means a key/model pair
                    // is already exhausted for the day, and the ladder is
                    // eating into its spares. That is the one number here
                    // worth catching your eye across a room.
                    bool burning = qu.IndexOf("quota",
                                       StringComparison.OrdinalIgnoreCase) >= 0;
                    _lblQuota.ForeColor = burning ? OFF_RED : TXT_DIM;
                    _lblQuota.Font = new Font("Segoe UI", 8.5F,
                                        burning ? FontStyle.Bold : FontStyle.Regular);
                }
                if (p != _personName)
                {
                    _personName = p;
                    foreach (var pair in _chips)
                        pair.Key.Text = FillPerson(pair.Value);
                }
                if (g != _gestureOn) { _gestureOn = g; PaintGesture(); }
            });
        }

        void RefreshDiary()
        {
            string reply = MemorySend("diary 8");
            if (reply == null || !reply.StartsWith("DIARY ")) return;
            string body = reply.Substring(6).Trim();
            if (body == _lastDiaryBlob) return;
            _lastDiaryBlob = body;

            string[] items = (body == "-")
                ? new string[] { "(nothing in the diary yet today)" }
                : body.Split(new string[] { " ;; " }, StringSplitOptions.RemoveEmptyEntries);

            UI(() =>
            {
                _lstDiary.Items.Clear();
                foreach (string it in items) _lstDiary.Items.Add(it);
                int vis = Math.Max(1, _lstDiary.ClientSize.Height
                                      / Math.Max(1, _lstDiary.ItemHeight));
                _lstDiary.TopIndex = Math.Max(0, _lstDiary.Items.Count - vis);
            });
        }

        void Alerts_DrawItem(object sender, DrawItemEventArgs e)
        {
            if (e.Index < 0) return;
            string text = _lstAlerts.Items[e.Index].ToString();
            bool sensitive = text.IndexOf("SENSITIVE",
                                 StringComparison.OrdinalIgnoreCase) >= 0;
            e.DrawBackground();
            using (SolidBrush b = new SolidBrush(sensitive ? OFF_RED : TXT))
                e.Graphics.DrawString(text, e.Font, b, e.Bounds);
        }

        void RefreshAlerts()
        {
            string reply = MemorySend("alerts 4");
            if (reply == null || !reply.StartsWith("ALERTS ")) return;
            string body = reply.Substring(7).Trim();
            if (body == _lastAlertBlob) return;
            _lastAlertBlob = body;

            string[] segs = body.Split(new string[] { " ;; " },
                                       StringSplitOptions.RemoveEmptyEntries);
            string count = "";
            var rows = new List<string>();
            foreach (string seg in segs)
            {
                if (seg.StartsWith("today="))
                {
                    string n = seg.Substring(6);
                    count = n + (n == "1" ? " entry today" : " entries today");
                }
                else rows.Add(seg);
            }
            if (rows.Count == 0) rows.Add("(nothing flagged today)");

            UI(() =>
            {
                _lblAlertCount.Text = count;
                _lstAlerts.Items.Clear();
                foreach (string r in rows) _lstAlerts.Items.Add(r);
                int vis = Math.Max(1, _lstAlerts.ClientSize.Height
                                      / Math.Max(1, _lstAlerts.ItemHeight));
                _lstAlerts.TopIndex = Math.Max(0, _lstAlerts.Items.Count - vis);
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
                    _lblQuota.Text = "";
                    _lblQuota.ForeColor = TXT_DIM;
                    _lblAlertCount.Text = "";
                }
            });
        }

        void UI(Action a)
        {
            if (this.InvokeRequired) this.BeginInvoke(a);
            else a();
        }

        private void MainForm_FormClosing(object sender, FormClosingEventArgs e)
        {
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