import wx
import wx.lib.mixins.inspection

import sys
import time
import os
import shutil

from cStringIO import StringIO
from threading import Thread
from collections import OrderedDict
import base64

from epics import caput, Motor
from epics.wx import EpicsFunction

from epics.wx.utils import (add_menu, pack, Closure, popup,
                            NumericCombo, SimpleText, FileSave, FileOpen,
                            SelectWorkdir, LTEXT, CEN, LCEN, RCEN, RIGHT)

from .configfile import StageConfig
from .icons import icons
from .controlpanel import ControlPanel
from .positionpanel import PositionPanel

from .imagepanel_fly2 import ImagePanel_Fly2
from .imagepanel_epicsAD import ImagePanel_EpicsAD
from .imagepanel_weburl import ImagePanel_URL

ALL_EXP  = wx.ALL|wx.EXPAND
CEN_ALL  = wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_CENTER_VERTICAL
LEFT_CEN = wx.ALIGN_LEFT|wx.ALIGN_CENTER_VERTICAL
LEFT_TOP = wx.ALIGN_LEFT|wx.ALIGN_TOP
LEFT_BOT = wx.ALIGN_LEFT|wx.ALIGN_BOTTOM
CEN_TOP  = wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_TOP
CEN_BOT  = wx.ALIGN_CENTER_HORIZONTAL|wx.ALIGN_BOTTOM



class StageFrame(wx.Frame):
    htmllog  = 'SampleStage.html'
    html_header = """<html><head><title>Sample Stage Log</title></head>
<meta http-equiv='Pragma'  content='no-cache'>
<meta http-equiv='Refresh' content='300'>
<body>
    """

    def __init__(self, inifile='SampleStage_autosave.ini', size=(1600, 800)):
        super(StageFrame, self).__init__(None, wx.ID_ANY,
                                         style=wx.DEFAULT_FRAME_STYLE,
                                         size=size)

        self.SetFont(wx.Font(10, wx.SWISS, wx.NORMAL, wx.BOLD, False))
        self.read_config(configfile=inifile) # , get_dir=True)
        self.create_frame(size=size)
        self.imgpanel.Start()

    def create_frame(self, size=(1600, 800)):
        "build main frame"
        self.create_menus()
        self.statusbar = self.CreateStatusBar(2, wx.CAPTION|wx.THICK_FRAME)
        self.statusbar.SetStatusWidths([-3, -1])

        for index in range(2):
            self.statusbar.SetStatusText('', index)
        config = self.config
        
        self.ctrlpanel = ControlPanel(self, 
                                      groups=config.get('stage_groups', None),
                                      config=config.get('stages', {}))

        if self.cam_type.startswith('fly2'):
            self.imgpanel  = ImagePanel_Fly2(self,
                                             camera_id=int(self.cam_fly2id),
                                             writer=self.write_framerate)
        elif self.cam_type.startswith('area'):
            self.imgpanel  = ImagePanel_EpicsAD(self, prefix=self.cam_adpref,
                                                writer=self.write_framerate)
        elif self.cam_type.startswith('webcam'):
            self.imgpanel  = ImagePanel_URL(self, url=self.cam_weburl,
                                            writer=self.write_framerate)
            
           
        self.pospanel  = PositionPanel(self,
                                       config=config.get('scandb', None))
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddMany([(self.ctrlpanel, 0, ALL_EXP|LEFT_CEN, 1),
                       (self.imgpanel,  3, ALL_EXP|LEFT_CEN, 1),
                       (self.pospanel,  1, ALL_EXP|LEFT_CEN, 1)])

        pack(self, sizer)
        self.SetSize(size)
        if len(self.iconfile) > 0:
            self.SetIcon(wx.Icon(self.iconfile, wx.BITMAP_TYPE_ICO))
        self.Bind(wx.EVT_CLOSE, self.onClose)

    def create_menus(self):
        "Create the menubar"
        mbar  = wx.MenuBar()
        fmenu = wx.Menu()
        omenu = wx.Menu()
        add_menu(self, fmenu, label="&Save", text="Save Configuration",
                 action = self.onSaveConfig)
        add_menu(self, fmenu, label="&Read", text="Read Configuration",
                 action = self.onReadConfig)

        fmenu.AppendSeparator()
        add_menu(self, fmenu, label="E&xit",  text="Quit Program",
                 action = self.onClose)

        vmove  = wx.NewId()
        verase = wx.NewId()
        vreplace = wx.NewId()
        self.menu_opts = {vmove: 'v_move', verase: 'v_erase',
                          vreplace: 'v_replace'}

        mitem = omenu.Append(vmove, "Verify Go To ",
                             "Prompt to Verify Moving with 'Go To'",
                             wx.ITEM_CHECK)
        mitem.Check()
        self.Bind(wx.EVT_MENU, self.onMenuOption, mitem)

        mitem = omenu.Append(verase, "Verify Erase",
                     "Prompt to Verify Erasing Positions", wx.ITEM_CHECK)
        mitem.Check()
        self.Bind(wx.EVT_MENU, self.onMenuOption, mitem)

        mitem = omenu.Append(vreplace, "Verify Overwrite",
                     "Prompt to Verify Overwriting Positions",  wx.ITEM_CHECK)
        mitem.Check()
        self.Bind(wx.EVT_MENU, self.onMenuOption, mitem)

        omenu.AppendSeparator()
        mbar.Append(fmenu, '&File')
        mbar.Append(omenu, '&Options')
        self.SetMenuBar(mbar)


    def onMenuOption(self, evt=None):
        """events for options menu: move, erase, overwrite """
        setattr(self, self.menu_opts[evt.GetId()], evt.Checked())

    def read_config(self, configfile=None, get_dir=False):
        "open/read ini config file"

        self.cnf = StageConfig(configfile)
        self.config = self.cnf.config
        gui = self.config['gui']
        self.workdir_file  = gui.get('workdir_file', 'sampleviewer_workdir.txt')
        self.iconfile      = gui.get('icon_file', '')
        self.autosave_file = gui.get('autosave_file', None)
        self.v_move    = gui.get('verify_move', True)
        self.v_erase   = gui.get('verify_erase', True)
        self.v_replace = gui.get('verify_overwrite', True)
        self.SetTitle(gui.get('title', 'Microscope'))

        cam = self.config['camera']
        self.imgdir     = cam.get('image_folder', 'Sample_Images')
        self.cam_type   = cam.get('type', 'fly2').lower()
        self.cam_fly2id = cam.get('fly2_id', 0)
        self.cam_adpref = cam.get('ad_prefix', '')
        self.cam_adform = cam.get('ad_format', 'JPEG')
        self.cam_weburl = cam.get('web_url', 'http://164.54.160.115/jpg/2/image.jpg')
        
        try:
            workdir = open(self.workdir_file, 'r').readline()[:-1]
            os.chdir(workdir)
        except:
            pass

        if get_dir:
            ret = SelectWorkdir(self)
            os.chdir(ret)

        if not os.path.exists(self.imgdir):
            os.makedirs(self.imgdir)
        if not os.path.exists(self.htmllog):
            self.begin_htmllog()

        self.config = self.cnf.config
        self.stages = OrderedDict()
        for mname, data in self.config.get('stages', {}).items():
            mot = Motor(name=mname)
            if data['prec'] is None:
                data['prec'] = mot.precision
            if data['desc'] is None:
                data['desc'] = mot.description
            if data['maxstep'] is None:
                data['maxstep'] = (mot.high_limit - mot.low_limit)/2.10
            self.stages[mname] = data

    def begin_htmllog(self):
        "initialize log file"
        fout = open(self.htmllog, 'w')
        fout.write(self.html_header)
        fout.close()

    def save_image(self, fname):
        "save image to file"
        imgdata = self.imgpanel.SaveImage(fname)
        if imgdata is None:
            self.write_message('could not save image to %s' % fname)
        else:
            self.write_message('saved image to %s' % fname)
        return imgdata

    def autosave(self, positions=None):
        self.cnf.Save('SampleStage_autosave.ini', positions=positions)

    def write_htmllog(self, name, thispos):
        stages  = self.config['stages']
        img_folder = self.config['camera']['image_folder']
        junk, img_file = os.path.split(thispos['image'])
        imgfile = os.path.join(img_folder, img_file)

        txt = []
        html_fmt ="""<hr>
    <table><tr><td><a href='%s'> <img src='%s' width=350></a></td>
    <td><table><tr><td>Position:</td><td>%s</td><td>%s</td></tr>
    <tr><td>Motor Name</td><td>PV Name</td><td>Value</td></tr>
    %s
    </table></td></tr></table>"""  
        pos_fmt ="    <tr><td> %s </td><td> %s </td><td>   %f</td></tr>" 
        for pvname, value in thispos['position'].items():
            txt.append(pos_fmt % (stages[pvname]['desc'], pvname, value))
       
        fout = open(self.htmllog, 'a')
        fout.write(html_fmt % (imgfile, imgfile, name, 
                               thispos['timestamp'],  '\n'.join(txt)))
        fout.close()

    def write_message(self, msg='', index=0):
        "write to status bar"
        self.statusbar.SetStatusText(msg, index)

    def write_framerate(self, msg):
        "write to status bar"
        self.statusbar.SetStatusText(msg, 1)


    def onClose(self, event=None):
        if wx.ID_YES == popup(self, "Really Quit?", "Exit Sample Stage?",
                              style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION):

            fout = open(self.workdir_file, 'w')
            fout.write("%s\n" % os.path.abspath(os.curdir))
            fout.close()
            self.imgpanel.Stop()
            self.Destroy()

    def onSaveConfig(self, event=None):
        fname = FileSave(self, 'Save Configuration File',
                         wildcard='INI (*.ini)|*.ini|All files (*.*)|*.*',
                         default_file='SampleStage.ini')
        if fname is not None:
            self.cnf.Save(fname)
        self.write_message('Saved Configuration File %s' % fname)


    def onReadConfig(self, event=None):
        fname = FileOpen(self, 'Read Configuration File',
                         wildcard='INI (*.ini)|*.ini|All files (*.*)|*.*',
                         default_file='SampleStage.ini')
        if fname is not None:
            self.read_config(fname)
            self.connect_motors()
            self.pospanel.set_positions(self.config['positions'])
        self.write_message('Read Configuration File %s' % fname)

class ViewerApp(wx.App, wx.lib.mixins.inspection.InspectionMixin):
    def __init__(self, inifile=None, debug=False, **kws):
        self.inifile = inifile
        self.debug = debug
        wx.App.__init__(self, **kws)

    def createApp(self):
        frame = StageFrame(inifile=self.inifile)
        frame.Show()
        self.SetTopWindow(frame)

    def OnInit(self):
        self.createApp()
        if self.debug:
            self.ShowInspectionTool()
        return True

if __name__ == '__main__':
    app = ViewerApp(inifile=None, debug=True)
    app.MainLoop()
