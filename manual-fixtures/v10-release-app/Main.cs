// 隔离的真实 Windows GUI 验收夹具，不包含被测计算器业务实现。
using System;
using System.IO;
using System.Windows.Forms;

class ReleaseFixture {
    [STAThread]
    static void Main(string[] args) {
        if (args.Length != 1 || !Directory.Exists(args[0])) Environment.Exit(2);
        Application.EnableVisualStyles();
        var form = new Form { Text = "LCA v1.0 隔离保存验收", Width = 480, Height = 220 };
        var input = new TextBox { Name = "DisplayName", AccessibleName = "验收内容", Left = 24, Top = 24, Width = 400 };
        var status = new Label { Name = "SaveStatus", AccessibleName = "保存状态", Text = "尚未保存", Left = 24, Top = 112, Width = 400 };
        var save = new Button { Name = "Save", AccessibleName = "保存", Text = "保存", Left = 24, Top = 64 };
        save.Click += (sender, e) => { File.WriteAllText(Path.Combine(args[0], "gui-saved.txt"), input.Text); status.Text = "已保存：" + input.Text; };
        form.Controls.AddRange(new Control[] { input, save, status });
        form.Shown += (sender, e) => { Console.WriteLine("LCA_GUI_READY pid=" + System.Diagnostics.Process.GetCurrentProcess().Id); Console.Out.Flush(); };
        Application.Run(form);
    }
}
