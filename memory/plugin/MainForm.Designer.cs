namespace Memory {
  partial class MainForm {
    /// <summary>
    /// Required designer variable.
    /// </summary>
    private System.ComponentModel.IContainer components = null;

    /// <summary>
    /// Clean up any resources being used.
    /// </summary>
    /// <param name="disposing">true if managed resources should be disposed; otherwise, false.</param>
    protected override void Dispose(bool disposing) {
      if (disposing && (components != null)) {
        components.Dispose();
      }
      base.Dispose(disposing);
    }

    #region Windows Form Designer generated code

    /// <summary>
    /// Required method for Designer support. The panel's controls are all
    /// built in code in the MainForm constructor; this only sets the window
    /// itself up and wires the close handler that shuts the socket and
    /// timers down cleanly.
    /// </summary>
    private void InitializeComponent() {
      this.SuspendLayout();
      //
      // MainForm
      //
      this.ClientSize = new System.Drawing.Size(712, 434);
      this.Name = "MainForm";
      this.Text = "Memory";
      this.FormClosing += new System.Windows.Forms.FormClosingEventHandler(this.MainForm_FormClosing);
      this.ResumeLayout(false);
    }

    #endregion
  }
}
