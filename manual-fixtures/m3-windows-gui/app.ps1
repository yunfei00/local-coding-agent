param([Parameter(Mandatory=$true)][string]$StatePath, [string]$Title = 'Local Agent M3 Fixture')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing,System.Web.Extensions -TypeDefinition @'
using System;
using System.IO;
using System.Drawing;
using System.Windows.Forms;
using System.Web.Script.Serialization;
public class M3Fixture : Form {
    public string StatePath;
    public int Clicks=0, ScrollEvents=0, ShortcutCount=0, Dangerous=0;
    public TextBox Entry;
    public Label Status;
    public Panel Scroller;
    public void Save() {
        File.WriteAllText(StatePath, new JavaScriptSerializer().Serialize(new {
            pid=System.Diagnostics.Process.GetCurrentProcess().Id, hwnd=Handle.ToInt64(),
            clicks=Clicks, text=Entry.Text, scroll=Scroller.VerticalScroll.Value,
            scroll_events=ScrollEvents, shortcuts=ShortcutCount, dangerous=Dangerous,
            status=Status.Text, left=Left, top=Top, width=Width, height=Height
        }));
    }
    public M3Fixture(string state, string title) {
        StatePath=state; Text=title; Name="M3Window";
        Width=620; Height=650; StartPosition=FormStartPosition.Manual; Location=new Point(90,80);
        AutoScaleMode=AutoScaleMode.Dpi; KeyPreview=true;
        Button settings=new Button {Name="SettingsButton",Text="Settings",Location=new Point(20,12),Size=new Size(120,32)};
        Status=new Label {Name="StatusLabel",Text="Home",Location=new Point(160,15),Size=new Size(390,28)};
        Entry=new TextBox {Name="NameInput",Location=new Point(20,62),Width=260,AccessibleName="Display name",Enabled=false};
        TextBox password=new TextBox {Name="PasswordInput",Location=new Point(310,62),Width=220,UseSystemPasswordChar=true,AccessibleName="Password"};
        Button delayed=new Button {Name="DelayedButton",Text="Wait for ready",Location=new Point(20,105),Size=new Size(140,32)};
        Button danger=new Button {Name="DeleteButton",Text="Delete record",Location=new Point(190,105),Size=new Size(140,32)};
        Scroller=new Panel {Name="ScrollPanel",Location=new Point(20,158),Size=new Size(550,400),AutoScroll=true,TabStop=true};
        for(int i=0;i<40;i++) Scroller.Controls.Add(new Label {Name="Row"+i,Text="Fixture row "+i,Location=new Point(10,i*35),Size=new Size(380,28)});
        Controls.AddRange(new Control[]{settings,Status,Entry,password,delayed,danger,Scroller});
        settings.Click+=(s,e)=>{Clicks++;Entry.Enabled=true;Status.Text="Settings ready";Save();};
        Entry.TextChanged+=(s,e)=>Save();
        danger.Click+=(s,e)=>{Dangerous++;Save();};
        Scroller.Scroll+=(s,e)=>{ScrollEvents++;Save();};
        Scroller.MouseWheel+=(s,e)=>{ScrollEvents++;BeginInvoke(new Action(Save));};
        KeyDown+=(s,e)=>{if(e.Control && e.KeyCode==Keys.K){ShortcutCount++;Status.Text="Shortcut OK";e.Handled=true;Save();}};
        Timer timer=new Timer {Interval=650};
        delayed.Click+=(s,e)=>{Status.Text="Waiting";delayed.Enabled=false;Save();timer.Start();};
        timer.Tick+=(s,e)=>{timer.Stop();delayed.Enabled=true;Status.Text="Ready after timer";Save();};
        Shown+=(s,e)=>{Save();Console.WriteLine("M3_GUI_READY");Console.Out.Flush();};
    }
}
'@
[System.Windows.Forms.Application]::EnableVisualStyles()
$m3Form = New-Object M3Fixture($StatePath, $Title)
[System.Windows.Forms.Application]::Run($m3Form)
