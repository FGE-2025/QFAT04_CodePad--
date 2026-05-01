"""FileTabplus.py — FileTab+ addon for QFAT04 CodePad"""
__version__ = "0.17"
import os, subprocess, sys
from qgis.PyQt.QtCore import Qt, QSettings, QTimer, QPoint, QEvent, QPropertyAnimation, QEasingCurve
from qgis.PyQt.QtGui import QFont, QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QMenu, QDialog,
    QFormLayout, QSpinBox, QFontComboBox, QCheckBox, QDialogButtonBox,
    QAbstractItemView, QPushButton, QApplication, QComboBox, QColorDialog,
    QHeaderView, QGroupBox, QLineEdit
)
from qgis.core import QgsProject
try:
    from qgis.PyQt import sip
except ImportError:
    try: import sip
    except ImportError: sip = None

_S = "QFAT/QFAT04/addon_tab_panel/"
SEC_OPEN, SEC_FAV_P, SEC_FAV_G, SEC_REC = "open", "fav_proj", "fav_glob", "recent"
SEC_LABEL = {SEC_OPEN: "Open Tabs", SEC_FAV_P: "Favourites (Project)",
             SEC_FAV_G: "Favourites (Global)", SEC_REC: "Recent"}
RK, RS, RP, RT, RL = (Qt.UserRole + i for i in range(1, 6))
ANIM = [("Instant", 0), ("Fast", 150), ("Medium", 300), ("Slow", 600)]
_SORT_KEYS_PATH = {
    "name_asc":  (lambda p: os.path.basename(p).lower(), False),
    "name_desc": (lambda p: os.path.basename(p).lower(), True),
    "ext":       (lambda p: (os.path.splitext(p)[1].lower(), os.path.basename(p).lower()), False),
    "path":      (lambda p: p.lower(), False),
    "folder":    (lambda p: (os.path.dirname(p).lower(), os.path.basename(p).lower()), False),
}
_SORT_KEYS_TAB = {
    "name_asc":  (lambda t: (t[1] or "").lower(), False),
    "name_desc": (lambda t: (t[1] or "").lower(), True),
    "ext":       (lambda t: (os.path.splitext(t[0] or "")[1].lower(), (t[1] or "").lower()), False),
    "path":      (lambda t: (t[0] or "").lower(), False),
    "folder":    (lambda t: (os.path.dirname(t[0] or "").lower(), (t[1] or "").lower()), False),
}

def _alive(d):
    if sip is None: return True
    try: return not sip.isdeleted(d) and not sip.isdeleted(d.tabs)
    except: return False

def _n(p):
    try: return os.path.normcase(os.path.abspath(p)) if p else ""
    except: return p or ""

def _pp(page):
    if page is None: return None
    for a in ("path", "file_path", "filepath", "filename", "file", "_path"):
        v = getattr(page, a, None)
        if v: return v
    for a in ("filePath", "get_path", "currentFile"):
        fn = getattr(page, a, None)
        if callable(fn):
            v = fn()
            if v: return v
    return None

def _shell_open(path, select=False):
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select," + os.path.normpath(path)] if select else ["explorer", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path] if select else ["open", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) if select else path])
    except: pass


class _Tree(QTreeWidget):
    def __init__(self, panel):
        super().__init__()
        self._p = panel
        self._ds = self._di = None; self._dd = False

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            it = self.itemAt(ev.pos())
            if it and it.data(0, RK) == "entry" and it.data(0, RS) == SEC_OPEN:
                self._ds, self._di, self._dd = QPoint(ev.pos()), it, False
            else:
                self._ds = self._di = None; self._dd = False
        elif ev.button() == Qt.MiddleButton:
            it = self.itemAt(ev.pos())
            if it and it.data(0, RK) == "entry" and it.data(0, RS) == SEC_OPEN:
                self._p._close_tab(it.data(0, RP) or None); return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._ds and self._di and (ev.buttons() & Qt.LeftButton):
            if (ev.pos() - self._ds).manhattanLength() > 6:
                if not self._dd:
                    self._dd = True; self.viewport().setCursor(Qt.ClosedHandCursor)
                tgt = self.itemAt(QPoint(self.indentation() + 4, ev.pos().y()))
                if (tgt and tgt is not self._di and tgt.data(0, RK) == "entry"
                        and tgt.data(0, RS) == SEC_OPEN and tgt.parent() is self._di.parent()):
                    self._swap(self._di, tgt); self.setCurrentItem(self._di)
                return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._di:
            was = self._dd; self._di = self._ds = None; self._dd = False
            try: self.viewport().unsetCursor()
            except: pass
            if was:
                self._p._syncing = False; self._p._sig = None; self._p.refresh(); return
        super().mouseReleaseEvent(ev)

    def _swap(self, a, b):
        par = a.parent()
        if not par or par is not b.parent(): return
        ia, ib = par.indexOfChild(a), par.indexOfChild(b)
        if ia < 0 or ib < 0 or ia == ib: return
        ta, tb = a.data(0, RT), b.data(0, RT)
        if ta is not None and tb is not None and ta >= 0 and tb >= 0:
            self._p._syncing = True
            try: self._p.dock.tabs.tabBar().moveTab(ta, tb)
            except: pass
            a.setData(0, RT, tb); b.setData(0, RT, ta)
        self.blockSignals(True)
        hi, lo = max(ia, ib), min(ia, ib)
        h, l = par.takeChild(hi), par.takeChild(lo)
        par.insertChild(lo, h); par.insertChild(hi, l)
        self.blockSignals(False)


class TabPanelWidget(QWidget):
    def __init__(self, dock):
        super().__init__()
        self.dock = dock
        self._gfavs, self._pfavs, self._recents = [], [], []
        self._collapsed, self._group = set(), False
        self._rlimit = 20
        self._ff, self._fs, self._fb = "Arial Narrow", 9, False
        self._deb, self._anim, self._off, self._off_r, self._ind = 120, 150, 8, 8, 8
        self._hide_branches = False; self._auto_scroll = True
        self._c = {"abg": QColor(0,0,0), "afg": QColor(255,255,255),
                    "d": QColor(230,160,60), "n": QColor(0,0,0), "s": QColor(0,0,0)}
        self._syncing = self._self_chg = False; self._sig = None; self._pending_scroll = None
        self._load()
        lay = QVBoxLayout(self); lay.setContentsMargins(2,2,2,2); lay.setSpacing(2)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter...")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self._filter)
        self.tree = _Tree(self)
        for fn, args in [
            ("setHeaderHidden", (True,)), ("setSelectionMode", (QAbstractItemView.ExtendedSelection,)),
            ("setDragDropMode", (QAbstractItemView.NoDragDrop,)),
            ("setContextMenuPolicy", (Qt.CustomContextMenu,)), ("setTextElideMode", (Qt.ElideNone,)),
            ("setHorizontalScrollBarPolicy", (Qt.ScrollBarAlwaysOn,)),
            ("setVerticalScrollBarPolicy", (Qt.ScrollBarAlwaysOn,)),
            ("setHorizontalScrollMode", (QAbstractItemView.ScrollPerPixel,)),
            ("setVerticalScrollMode", (QAbstractItemView.ScrollPerPixel,)),
            ("setAutoScroll", (False,))]:
            getattr(self.tree, fn)(*args)
        self.tree.header().setStretchLastSection(False)
        try: self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        except: pass
        lay.addWidget(self.tree, 1)
        self.tree.itemClicked.connect(self._click)
        self.tree.itemDoubleClicked.connect(self._dblclick)
        self.tree.itemExpanded.connect(self._exp)
        self.tree.itemCollapsed.connect(self._exp)
        self.tree.customContextMenuRequested.connect(self._ctx)
        self.tree.installEventFilter(self)
        self._stimer = QTimer(self); self._stimer.setSingleShot(True)
        self._stimer.timeout.connect(self._scroll_now)
        self._va = self._ha = None
        self.setObjectName("filetab_plus_widget"); self._apply()

    # --- settings ---
    def _load(self):
        s = QSettings()
        g = lambda k, d, t=str: s.value(_S+k, d, type=t) if t != str else s.value(_S+k, d)
        self._rlimit = int(g("recent_limit", 20, int))
        self._ff, self._fs, self._fb = g("font_family","Arial Narrow"), int(g("font_size",9,int)), g("font_bold",False,bool)
        self._group = g("group_by_folder", False, bool)
        self._gfavs = list(g("global_favs", [], list) or [])
        self._recents = list(g("recents", [], list) or [])
        self._collapsed = set(g("collapsed", [], list) or [])
        self._deb, self._anim = int(g("scroll_debounce_ms",120,int)), int(g("scroll_anim_ms",150,int))
        self._off, self._off_r, self._ind = int(g("scroll_left_offset",8,int)), int(g("scroll_right_offset",8,int)), int(g("indent",8,int))
        self._hide_branches, self._auto_scroll = g("hide_branches",False,bool), g("auto_scroll",True,bool)
        for ck, df in [("abg","#000000"),("afg","#FFFFFF"),("d","#E6A03C"),("n","#000000"),("s","#000000")]:
            self._c[ck] = QColor(g("color_"+ck, df))

    def _save(self):
        s = QSettings()
        vals = [("recent_limit",self._rlimit),("font_family",self._ff),("font_size",self._fs),
            ("font_bold",self._fb),("group_by_folder",self._group),("global_favs",self._gfavs),
            ("recents",self._recents[:self._rlimit]),("collapsed",list(self._collapsed)),
            ("scroll_debounce_ms",self._deb),("scroll_anim_ms",self._anim),
            ("scroll_left_offset",self._off),("scroll_right_offset",self._off_r),("indent",self._ind),
            ("hide_branches",self._hide_branches),("auto_scroll",self._auto_scroll)]
        vals += [("color_"+k, v.name(QColor.HexArgb) if k=="abg" else v.name()) for k,v in self._c.items()]
        for k,v in vals: s.setValue(_S+k, v)

    def load_pfavs(self):
        raw, ok = QgsProject.instance().readEntry("qfat_filetab_plus", "project_favs", "")
        self._pfavs = [p for p in raw.split("|") if p] if (ok and raw) else []

    def save_pfavs(self):
        QgsProject.instance().writeEntry("qfat_filetab_plus", "project_favs", "|".join(self._pfavs))

    def _apply(self):
        f = QFont(self._ff, self._fs); f.setBold(self._fb)
        self.tree.setFont(f); self.tree.setIndentation(self._ind)
        self.tree.setStyleSheet(
            "QTreeWidget::branch{border:none;width:0;padding:0;margin:0;image:none;}"
            "QTreeWidget::branch:has-siblings:!adjoins-item{image:none;}"
            "QTreeWidget::branch:has-siblings:adjoins-item{image:none;}"
            "QTreeWidget::branch:!has-children:!has-siblings:adjoins-item{image:none;}"
            "QTreeWidget::branch:has-children:!has-siblings:closed,"
            "QTreeWidget::branch:closed:has-children:has-siblings{image:none;}"
            "QTreeWidget::branch:open:has-children:!has-siblings,"
            "QTreeWidget::branch:open:has-children:has-siblings{image:none;}"
            if self._hide_branches else "")

    def _apply_filter(self, text=""):
        filt = text.strip().lower() if text else ""
        def walk(it):
            if it.data(0, RK) == "entry":
                lbl = (it.data(0, RL) or "").lower()
                path = (it.data(0, RP) or "").lower()
                vis = not filt or filt in lbl or filt in path
                it.setHidden(not vis)
            elif it.data(0, RK) in ("section", "group"):
                any_vis = False
                for i in range(it.childCount()):
                    walk(it.child(i))
                    if not it.child(i).isHidden(): any_vis = True
                it.setHidden(not any_vis and bool(filt))
        for i in range(self.tree.topLevelItemCount()): walk(self.tree.topLevelItem(i))

    # --- data helpers ---
    def _tabs(self):
        if not _alive(self.dock): return []
        return [((_pp(w:=self.dock.tabs.widget(i))),
                 os.path.basename(p) if (p:=_pp(w)) else (self.dock.tabs.tabText(i) or "<tab %d>"%i), i)
                for i in range(self.dock.tabs.count())]

    def _paths(self):
        return [_pp(self.dock.tabs.widget(i)) for i in range(self.dock.tabs.count())] if _alive(self.dock) else []

    def _cur_path(self):
        if not _alive(self.dock): return None
        i = self.dock.tabs.currentIndex()
        return _pp(self.dock.tabs.widget(i)) if i >= 0 else None

    # --- tree build ---
    def refresh(self):
        if not _alive(self.dock): return
        self._pending_scroll = None  # item refs become stale
        self.tree.blockSignals(True); self.tree.clear()
        self._sec_tabs(SEC_OPEN, self._tabs())
        for sid, ps in [(SEC_FAV_P,self._pfavs),(SEC_FAV_G,self._gfavs),(SEC_REC,self._recents[:self._rlimit])]:
            h = self._hdr(sid)
            for p in ps:
                if p: self._ent(h, sid, p, os.path.basename(p))
        self.tree.blockSignals(False); self._upd()
        self._apply_filter(self._filter.text())
        self.sched()

    def _hdr(self, sid):
        it = QTreeWidgetItem([SEC_LABEL[sid]])
        it.setData(0,RK,"section"); it.setData(0,RS,sid)
        f = it.font(0); f.setBold(True); it.setFont(0,f)
        it.setForeground(0, QBrush(self._c["s"])); it.setFlags(Qt.ItemIsEnabled)
        self.tree.addTopLevelItem(it); it.setExpanded(sid not in self._collapsed)
        return it

    def _sec_tabs(self, sid, tabs):
        h = self._hdr(sid)
        if self._group:
            grps, order = {}, []
            for p,lbl,i in tabs:
                k = (os.path.dirname(p) or "<root>") if p else "<untitled>"
                grps.setdefault(k,[]).append((p,lbl,i))
                if k not in order: order.append(k)
            for k in order:
                gi = QTreeWidgetItem([k])
                gi.setData(0,RK,"group"); gi.setData(0,RS,SEC_OPEN); gi.setFlags(Qt.ItemIsEnabled)
                h.addChild(gi)
                for p,lbl,i in grps[k]: self._ent(gi, sid, p, lbl, i)
                gi.setExpanded(True)
        else:
            for p,lbl,i in tabs: self._ent(h, sid, p, lbl, i)

    def _ent(self, par, sid, path, label, tidx=-1):
        it = QTreeWidgetItem([label])
        it.setData(0,RK,"entry"); it.setData(0,RS,sid); it.setData(0,RP,path or "")
        it.setData(0,RL,label); it.setData(0,RT,tidx)
        it.setToolTip(0, self._tip(path, label))
        it.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable); par.addChild(it)

    @staticmethod
    def _tip(path, label):
        if not path: return label
        lines = [path]
        try:
            st = os.stat(path)
            sz = st.st_size
            if sz < 1024: lines.append("Size: %d B" % sz)
            elif sz < 1048576: lines.append("Size: %.1f KB" % (sz/1024))
            else: lines.append("Size: %.1f MB" % (sz/1048576))
            from datetime import datetime
            lines.append("Modified: " + datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"))
        except: pass
        return "\n".join(lines)

    # --- active/dirty ---
    def _upd(self):
        if not _alive(self.dock): return
        if not self._syncing:
            sig = [(i,_pp(self.dock.tabs.widget(i)),self.dock.tabs.tabText(i)) for i in range(self.dock.tabs.count())]
            if sig != self._sig: self._sig = sig; self.refresh(); return
        ci = self.dock.tabs.currentIndex()
        cp = _pp(self.dock.tabs.widget(ci)) if ci >= 0 else None
        dirty = set()
        for i in range(self.dock.tabs.count()):
            w = self.dock.tabs.widget(i)
            try:
                if w.is_modified(): p=_pp(w); dirty.add(_n(p) if p else i)
            except: pass
        C = self._c
        def walk(it):
            if it.data(0,RK) == "entry":
                s,p,lbl = it.data(0,RS), it.data(0,RP) or None, it.data(0,RL) or ""
                ti = it.data(0,RT) or -1
                act = s==SEC_OPEN and ((p and cp and _n(p)==_n(cp)) or (not p and ti>=0 and ti==ci))
                drt = (_n(p) in dirty) if p else (ti in dirty)
                it.setText(0, ("● " if drt else "   ")+lbl)
                it.setBackground(0, QBrush(C["abg"]) if act else QBrush())
                it.setForeground(0, QBrush(C["afg"] if act else (C["d"] if drt else C["n"])))
                f = it.font(0); f.setBold(act); it.setFont(0,f)
            for i in range(it.childCount()): walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()): walk(self.tree.topLevelItem(i))

    # --- scrolling ---
    def sched(self):
        if not self._auto_scroll: return
        if self._deb <= 0: self._scroll_now()
        else: self._stimer.start(self._deb)

    def _scroll_now(self):
        if not _alive(self.dock): return
        ps = self._pending_scroll; self._pending_scroll = None
        if ps: self._scroll_to(*ps); return
        ci = self.dock.tabs.currentIndex()
        if ci < 0: return
        tgt = self._find(_pp(self.dock.tabs.widget(ci)), ci)
        if not tgt: return
        # skip if item text fully visible
        rect = self.tree.visualItemRect(tgt)
        fm = self.tree.fontMetrics()
        tw = fm.horizontalAdvance(tgt.text(0)) + 4
        text_left = rect.left()
        text_right = text_left + tw
        vw = self.tree.viewport().width()
        vh = self.tree.viewport().height()
        if text_left >= 0 and text_right <= vw and rect.top() >= 0 and rect.bottom() <= vh: return
        self._scroll_to(tgt)

    def _find(self, cp, ci):
        r = [None]
        def w(it):
            if r[0]: return
            if it.data(0,RK)=="entry" and it.data(0,RS)==SEC_OPEN:
                p,ti = it.data(0,RP) or None, it.data(0,RT) or -1
                if (p and cp and _n(p)==_n(cp)) or (not p and ti>=0 and ti==ci): r[0]=it
            for i in range(it.childCount()): w(it.child(i))
        for i in range(self.tree.topLevelItemCount()): w(self.tree.topLevelItem(i))
        return r[0]

    def _scroll_to(self, tgt, h_zero=False, h_align="left"):
        if not tgt: return
        try:
            if sip and sip.isdeleted(tgt): return
        except: pass
        rect = self.tree.visualItemRect(tgt)
        vb, hb = self.tree.verticalScrollBar(), self.tree.horizontalScrollBar()
        vh, vw = self.tree.viewport().height(), self.tree.viewport().width()
        nv = max(vb.minimum(), min(vb.maximum(), vb.value()+rect.top()-max(0,(vh-rect.height())//2)))
        # compute actual text right edge (not column right which is longest item)
        fm = self.tree.fontMetrics()
        tw = fm.horizontalAdvance(tgt.text(0))
        text_left = rect.left()
        text_right = text_left + tw + 4
        if h_zero: nh = 0
        elif h_align == "right":
            # align this item's text right edge to viewport right
            abs_right = hb.value() + text_right
            nh = max(hb.minimum(), min(hb.maximum(), abs_right - vw + max(0, self._off_r)))
        else:
            abs_left = hb.value() + text_left
            nh = max(hb.minimum(), min(hb.maximum(), abs_left - max(0, self._off)))
        if self._anim <= 0:
            self.tree.scrollToItem(tgt, QAbstractItemView.PositionAtCenter); hb.setValue(nh); return
        for bar, nval, attr in [(vb,nv,"_va"),(hb,nh,"_ha")]:
            if int(nval)==bar.value(): continue
            old = getattr(self, attr)
            if old:
                try: old.stop()
                except: pass
            a = QPropertyAnimation(bar, b"value", self)
            a.setDuration(self._anim); a.setStartValue(bar.value()); a.setEndValue(int(nval))
            a.setEasingCurve(QEasingCurve.OutCubic); a.start(); setattr(self, attr, a)

    # --- events ---
    def _click(self, it, col):
        k = it.data(0, RK)
        if k in ("group","section"):
            self._pending_scroll = (it, True, "left"); self.sched(); return
        if k == "entry":
            if it.data(0,RS)==SEC_OPEN: self._activate(it)
            # only scroll if tab name extends beyond viewport
            rect = self.tree.visualItemRect(it)
            fm = self.tree.fontMetrics()
            tw = fm.horizontalAdvance(it.text(0)) + 4
            text_left = rect.left()
            text_right = text_left + tw
            vw = self.tree.viewport().width()
            if text_left >= 0 and text_right <= vw: return  # text fully visible
            gpos = self.tree.viewport().mapFromGlobal(self.tree.cursor().pos())
            self._pending_scroll = (it, False, "left" if gpos.x() < self.tree.viewport().width()//2 else "right")
            self.sched()

    def _dblclick(self, it, col):
        if it.data(0,RK)!="entry": return
        p = it.data(0,RP) or None
        if it.data(0,RS) in (SEC_FAV_P,SEC_FAV_G,SEC_REC) and p and os.path.exists(p):
            self.dock.open_paths([p])

    def _exp(self, it):
        if it.data(0,RK)!="section": return
        s = it.data(0,RS)
        self._collapsed.discard(s) if it.isExpanded() else self._collapsed.add(s)
        self._save()

    def _activate(self, it):
        if not _alive(self.dock): return
        p, ti = it.data(0,RP) or None, it.data(0,RT) or -1
        self._self_chg = True
        try:
            if p:
                for i in range(self.dock.tabs.count()):
                    wp = _pp(self.dock.tabs.widget(i))
                    if wp and _n(wp)==_n(p): self.dock.tabs.setCurrentIndex(i); return
            if 0 <= ti < self.dock.tabs.count(): self.dock.tabs.setCurrentIndex(ti)
        finally: QTimer.singleShot(0, lambda: setattr(self,"_self_chg",False))

    def eventFilter(self, obj, ev):
        if obj is self.tree and ev.type()==QEvent.KeyPress:
            sel = [i for i in self.tree.selectedItems() if i.data(0,RK)=="entry"]
            if not sel: return False
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                if sel[0].data(0,RS)==SEC_OPEN: self._click(sel[0],0)
                else:
                    ps = [i.data(0,RP) for i in sel if i.data(0,RP) and os.path.exists(i.data(0,RP))]
                    if ps: self.dock.open_paths(ps)
                return True
            if ev.key()==Qt.Key_Delete: self._del_sel(sel); return True
        return False

    # --- actions ---
    def _close_tab(self, path):
        if not _alive(self.dock): return
        for i in range(self.dock.tabs.count()):
            wp = _pp(self.dock.tabs.widget(i))
            if path and wp and _n(wp)==_n(path): self.dock.tabs.tabCloseRequested.emit(i); return

    def _close_others(self, keep):
        for p in self._paths():
            if not p or (keep and _n(p)==_n(keep)): continue
            self._close_tab(p)

    def _close_right(self, anchor):
        found = False
        for p in self._paths():
            if found and p: self._close_tab(p)
            if p and anchor and _n(p)==_n(anchor): found = True

    def _close_all(self):
        if not _alive(self.dock): return
        for i in range(self.dock.tabs.count()-1, -1, -1):
            self.dock.tabs.tabCloseRequested.emit(i)

    def _save_all(self):
        if not _alive(self.dock): return
        for i in range(self.dock.tabs.count()):
            w = self.dock.tabs.widget(i)
            try:
                if hasattr(w, "save") and w.is_modified(): w.save()
            except: pass

    def _rename_file(self, path):
        if not path or not os.path.exists(path): return
        from qgis.PyQt.QtWidgets import QInputDialog
        old_name = os.path.basename(path)
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=old_name)
        if not ok or not new_name or new_name == old_name: return
        new_path = os.path.join(os.path.dirname(path), new_name)
        if os.path.exists(new_path):
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Rename", "File already exists: " + new_name)
            return
        try:
            os.rename(path, new_path)
        except Exception as e:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Rename", "Failed: " + str(e))
            return
        # update tab if open
        if _alive(self.dock):
            for i in range(self.dock.tabs.count()):
                w = self.dock.tabs.widget(i)
                wp = _pp(w)
                if wp and _n(wp) == _n(path):
                    if hasattr(w, "path"): w.path = new_path
                    self.dock.tabs.setTabText(i, new_name)
                    break
        # update favs/recents
        for lst in [self._pfavs, self._gfavs, self._recents]:
            for j, p in enumerate(lst):
                if p and _n(p) == _n(path): lst[j] = new_path
        self.save_pfavs(); self._save(); self.refresh()

    def _mod_list(self, lst, ps, add=True):
        c = False
        for p in ps:
            if add:
                if p and p not in lst: lst.append(p); c = True
            else:
                if p in lst: lst.remove(p); c = True
        return c

    def _fav_op(self, lst_attr, ps, add, is_proj=False):
        lst = getattr(self, lst_attr)
        if self._mod_list(lst, ps, add):
            (self.save_pfavs if is_proj else self._save)(); self.refresh()

    def _del_sel(self, sel):
        for it in list(sel):
            s, p = it.data(0,RS), it.data(0,RP) or None
            if s==SEC_OPEN: self._close_tab(p)
            elif s==SEC_FAV_P and p in self._pfavs: self._pfavs.remove(p)
            elif s==SEC_FAV_G and p in self._gfavs: self._gfavs.remove(p)
            elif s==SEC_REC and p in self._recents: self._recents.remove(p)
        self.save_pfavs(); self._save(); self.refresh()

    def push_recent(self, path):
        if not path: return
        if path in self._recents: self._recents.remove(path)
        self._recents.insert(0, path)
        self._recents = self._recents[:self._rlimit*2]; self._save()

    # --- sorting ---
    def _sort(self, sid, mode):
        if sid == SEC_OPEN: return self._sort_tabs(mode)
        lst = {SEC_FAV_P:self._pfavs, SEC_FAV_G:self._gfavs, SEC_REC:self._recents}.get(sid)
        if not lst: return
        if mode == "added_asc": lst.reverse()
        elif mode != "added_desc":
            kf, rev = _SORT_KEYS_PATH.get(mode, (None, False))
            if kf: lst.sort(key=kf, reverse=rev)
        (self.save_pfavs if sid==SEC_FAV_P else self._save)(); self.refresh()

    def _sort_tabs(self, mode):
        if not _alive(self.dock): return
        kf, rev = _SORT_KEYS_TAB.get(mode, (None, False))
        if not kf: return
        tabs = self._tabs(); tabs.sort(key=kf, reverse=rev)
        self._syncing = True
        try:
            tb = self.dock.tabs.tabBar()
            for ti, (path,lbl,oi) in enumerate(tabs):
                if ti >= self.dock.tabs.count(): break
                cur = -1
                for i in range(ti, self.dock.tabs.count()):
                    wp = _pp(self.dock.tabs.widget(i))
                    if (path and wp and _n(wp)==_n(path)) or (not path and not wp): cur=i; break
                if cur > ti: tb.moveTab(cur, ti)
        finally: self._syncing = False; self._sig = None; self.refresh()

    # --- context menus ---
    def _ctx(self, pos):
        it = self.tree.itemAt(pos)
        if not it or it.data(0,RK)=="section":
            return self._ctx_blank(pos, it.data(0,RS) if it else None)
        if it.data(0,RK)=="group": return self._ctx_group(it, pos)
        if it.data(0,RK)!="entry": return self._ctx_blank(pos)
        sel = [i for i in self.tree.selectedItems() if i.data(0,RK)=="entry"]
        if it not in sel: self.tree.clearSelection(); it.setSelected(True); sel = [it]
        ps = [s.data(0,RP) or None for s in sel]
        secs = {s.data(0,RS) for s in sel}
        multi = len(sel)>1; m = QMenu(self.tree); tag = " (%d)"%len(sel) if multi else ""
        if SEC_OPEN in secs:
            sc = list(zip(ps,[s.data(0,RS) for s in sel]))
            m.addAction("Close"+tag).triggered.connect(lambda: [self._close_tab(p) for p,s in sc if s==SEC_OPEN])
            if not multi:
                m.addAction("Close Others").triggered.connect(lambda: self._close_others(ps[0]))
                m.addAction("Close to the Right").triggered.connect(lambda: self._close_right(ps[0]))
        rps = [p for p in ps if p]
        if rps:
            m.addSeparator()
            m.addAction(("Copy Paths" if multi else "Copy Path")+tag).triggered.connect(lambda: QApplication.clipboard().setText("\n".join(rps)))
            if not multi:
                m.addAction("Copy Filename").triggered.connect(lambda: QApplication.clipboard().setText(os.path.basename(rps[0])))
                m.addAction("Reveal in Explorer").triggered.connect(lambda: _shell_open(rps[0], select=True))
                m.addAction("Rename...").triggered.connect(lambda: self._rename_file(rps[0]))
            m.addSeparator()
            fm = m.addMenu("Add to Favourites"+tag)
            fm.addAction("Project").triggered.connect(lambda: self._fav_op("_pfavs",rps,True,True))
            fm.addAction("Global").triggered.connect(lambda: self._fav_op("_gfavs",rps,True))
            if SEC_FAV_P in secs: m.addAction("Remove from Project Favs"+tag).triggered.connect(lambda: self._fav_op("_pfavs",rps,False,True))
            if SEC_FAV_G in secs: m.addAction("Remove from Global Favs"+tag).triggered.connect(lambda: self._fav_op("_gfavs",rps,False))
            if SEC_REC in secs: m.addAction("Remove from Recent"+tag).triggered.connect(lambda: self._fav_op("_recents",rps,False))
        m.exec_(self.tree.viewport().mapToGlobal(pos))

    def _ctx_group(self, gi, pos):
        ps = [gi.child(i).data(0,RP) for i in range(gi.childCount()) if gi.child(i).data(0,RK)=="entry" and gi.child(i).data(0,RP)]
        m = QMenu(self.tree)
        if ps:
            m.addAction("Close All (%d)"%len(ps)).triggered.connect(lambda: [self._close_tab(p) for p in ps])
            m.addSeparator()
            m.addAction("Add All to Project Favs").triggered.connect(lambda: self._fav_op("_pfavs",ps,True,True))
            m.addAction("Add All to Global Favs").triggered.connect(lambda: self._fav_op("_gfavs",ps,True))
            m.addAction("Copy All Paths").triggered.connect(lambda: QApplication.clipboard().setText("\n".join(ps)))
            m.addSeparator()
        m.addAction("Collapse" if gi.isExpanded() else "Expand").triggered.connect(lambda: gi.setExpanded(not gi.isExpanded()))
        d = gi.text(0)
        if d and os.path.isdir(d):
            m.addSeparator(); m.addAction("Reveal Folder").triggered.connect(lambda: _shell_open(d))
        m.exec_(self.tree.viewport().mapToGlobal(pos))

    def _ctx_blank(self, pos, sid=None):
        m = QMenu(self.tree)
        m.addAction("Refresh").triggered.connect(self.refresh)
        m.addSeparator()
        m.addAction("Expand All").triggered.connect(self.tree.expandAll)
        m.addAction("Collapse All").triggered.connect(self.tree.collapseAll)
        cp = self._cur_path()
        if cp:
            m.addSeparator()
            m.addAction("Add Current to Project Favs").triggered.connect(lambda: self._fav_op("_pfavs",[cp],True,True))
            m.addAction("Add Current to Global Favs").triggered.connect(lambda: self._fav_op("_gfavs",[cp],True))
        if sid == SEC_OPEN:
            m.addSeparator()
            all_ps = [p for p in self._paths() if p]
            m.addAction("Close All (%d)" % self.dock.tabs.count()).triggered.connect(self._close_all)
            m.addAction("Save All").triggered.connect(self._save_all)
        if sid in (SEC_FAV_P, SEC_FAV_G, SEC_REC):
            ps_map = {SEC_FAV_P: self._pfavs, SEC_FAV_G: self._gfavs, SEC_REC: self._recents[:self._rlimit]}
            open_ps = [p for p in ps_map.get(sid, []) if p and os.path.exists(p)]
            if open_ps:
                m.addSeparator()
                m.addAction("Open All (%d)" % len(open_ps)).triggered.connect(lambda: self.dock.open_paths(open_ps))
        if sid in (SEC_FAV_P, SEC_FAV_G, SEC_REC, SEC_OPEN):
            m.addSeparator()
            sm = m.addMenu("Sort")
            for label, mode in [("By Name (A→Z)","name_asc"),("By Name (Z→A)","name_desc"),
                ("By Extension","ext"),("By Path","path"),("By Folder","folder")]:
                sm.addAction(label).triggered.connect(lambda _=False, md=mode: self._sort(sid, md))
            if sid != SEC_OPEN:
                sm.addAction("By Added (newest)").triggered.connect(lambda: self._sort(sid,"added_desc"))
                sm.addAction("By Added (oldest)").triggered.connect(lambda: self._sort(sid,"added_asc"))
        m.addSeparator()
        clear_map = {SEC_FAV_P: ("Clear Project Favourites","_pfavs",True),
                     SEC_FAV_G: ("Clear Global Favourites","_gfavs",False),
                     SEC_REC: ("Clear Recents","_recents",False)}
        if sid in clear_map:
            lbl, attr, is_p = clear_map[sid]
            m.addAction(lbl).triggered.connect(lambda: (setattr(self,attr,[]), (self.save_pfavs() if is_p else self._save()), self.refresh()))
        else:
            m.addAction("Clear Recents").triggered.connect(lambda: (setattr(self,"_recents",[]), self._save(), self.refresh()))
        m.addSeparator()
        m.addAction("Settings...").triggered.connect(lambda: _SettingsDialog(self, self.dock).exec_())
        m.exec_(self.tree.viewport().mapToGlobal(pos))


class _SettingsDialog(QDialog):
    def __init__(self, w, parent=None):
        super().__init__(parent); self.setWindowTitle("FileTab+ Settings"); self.w = w
        main = QVBoxLayout(self)
        # Display
        gb1 = QGroupBox("Display"); f1 = QFormLayout()
        self.cb_f = QFontComboBox(); self.cb_f.setCurrentFont(QFont(w._ff)); f1.addRow("Font:",self.cb_f)
        self.sp_fs = QSpinBox(); self.sp_fs.setRange(6,32); self.sp_fs.setValue(w._fs); f1.addRow("Size:",self.sp_fs)
        self.chk_b = QCheckBox(); self.chk_b.setChecked(w._fb); f1.addRow("Bold:",self.chk_b)
        self.sp_ind = QSpinBox(); self.sp_ind.setRange(0,40); self.sp_ind.setSuffix(" px"); self.sp_ind.setValue(w._ind); f1.addRow("Indent:",self.sp_ind)
        self.chk_hb = QCheckBox(); self.chk_hb.setChecked(w._hide_branches); f1.addRow("Hide branches:",self.chk_hb)
        self.chk_g = QCheckBox(); self.chk_g.setChecked(w._group); f1.addRow("Group by folder:",self.chk_g)
        gb1.setLayout(f1); main.addWidget(gb1)
        # Colors
        gb2 = QGroupBox("Colors"); f2 = QFormLayout(); self._colors = {}
        for k, lbl in [("abg","Active bg:"),("afg","Active text:"),("d","Dirty:"),("n","Normal:"),("s","Section:")]:
            btn = QPushButton(); btn.setFixedSize(60,24); self._colors[k] = QColor(w._c[k])
            btn.setStyleSheet("background-color:%s;"%w._c[k].name())
            btn.clicked.connect(lambda _,ck=k,b=btn: self._pick(ck,b)); f2.addRow(lbl, btn)
        gb2.setLayout(f2); main.addWidget(gb2)
        # Scrolling
        gb3 = QGroupBox("Scrolling"); f3 = QFormLayout()
        self.chk_as = QCheckBox(); self.chk_as.setChecked(w._auto_scroll); f3.addRow("Auto-scroll:",self.chk_as)
        self.sp_deb = QSpinBox(); self.sp_deb.setRange(0,2000); self.sp_deb.setSuffix(" ms"); self.sp_deb.setValue(w._deb); f3.addRow("Debounce:",self.sp_deb)
        self.cb_a = QComboBox(); ci=0
        for i,(l,ms) in enumerate(ANIM):
            self.cb_a.addItem(l,ms)
            if ms==w._anim: ci=i
        self.cb_a.setCurrentIndex(ci); f3.addRow("Animation:",self.cb_a)
        self.sp_off = QSpinBox(); self.sp_off.setRange(0,200); self.sp_off.setSuffix(" px"); self.sp_off.setValue(w._off); f3.addRow("Left offset:",self.sp_off)
        self.sp_off_r = QSpinBox(); self.sp_off_r.setRange(0,200); self.sp_off_r.setSuffix(" px"); self.sp_off_r.setValue(w._off_r); f3.addRow("Right offset:",self.sp_off_r)
        gb3.setLayout(f3); main.addWidget(gb3)
        # Data
        gb4 = QGroupBox("Data"); f4 = QFormLayout()
        self.sp_rec = QSpinBox(); self.sp_rec.setRange(0,500); self.sp_rec.setValue(w._rlimit); f4.addRow("Recent count:",self.sp_rec)
        gb4.setLayout(f4); main.addWidget(gb4)
        bb = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject); main.addWidget(bb)

    def _pick(self, k, btn):
        opt = QColorDialog.ShowAlphaChannel if k=="abg" else QColorDialog.ColorDialogOptions()
        c = QColorDialog.getColor(self._colors[k], self, "Pick", opt)
        if c.isValid(): self._colors[k]=c; btn.setStyleSheet("background-color:%s;"%c.name())

    def _ok(self):
        w = self.w
        w._ff, w._fs, w._fb = self.cb_f.currentFont().family(), self.sp_fs.value(), self.chk_b.isChecked()
        w._ind, w._hide_branches, w._group = self.sp_ind.value(), self.chk_hb.isChecked(), self.chk_g.isChecked()
        w._auto_scroll = self.chk_as.isChecked()
        w._deb, w._anim, w._off, w._off_r = self.sp_deb.value(), int(self.cb_a.currentData()), self.sp_off.value(), self.sp_off_r.value()
        w._rlimit = self.sp_rec.value()
        for k in self._colors: w._c[k] = self._colors[k]
        w._save(); w._apply(); w.refresh(); self.accept()


# --- module state ---
_widget = _dock_ref = _dirty_timer = None
_wired = _view_menu_done = False
_handlers = dict.fromkeys(["current_changed","tab_close","tabs_moved","read_project","write_project","clear_project"])

def _find_vmenu(dock):
    for src in [getattr(dock,"inner_window",None), getattr(getattr(dock,"iface",None),"mainWindow",lambda:None)()]:
        if src is None: continue
        try:
            for a in src.menuBar().actions():
                sub = a.menu()
                if sub and a.text().replace("&","").strip().lower()=="view": return sub
        except: pass

def _reg_view(dock):
    global _view_menu_done
    if _view_menu_done or not _widget: return
    try:
        from qgis.PyQt.QtWidgets import QDockWidget
        qd = None
        try: qd = dock.get_panel("FileTabplus")
        except: pass
        if not qd:
            p = _widget.parent()
            while p:
                if isinstance(p, QDockWidget): qd=p; break
                p = p.parent()
        if not qd: return
        qd.setObjectName("filetab_plus_dock")
        vm = _find_vmenu(dock)
        if not vm: return
        act = qd.toggleViewAction(); act.setText("FileTab+")
        for e in vm.actions():
            if e.text()==act.text(): _view_menu_done=True; return
        after = None
        for a in vm.actions():
            if "maintoolbar" in a.text().replace(" ","").lower(): after=a; break
        if after:
            actions = vm.actions(); idx = actions.index(after)
            vm.insertAction(actions[idx+1], act) if idx+1 < len(actions) else vm.addAction(act)
        else: vm.addAction(act)
        _view_menu_done = True
    except: pass

_rtimer = None
def _try_view(dock):
    global _rtimer
    _reg_view(dock)
    if _view_menu_done: return
    _rtimer = QTimer(); _rtimer.setSingleShot(False); _rtimer.setInterval(500); n=[0]
    def t(): n[0]+=1; _reg_view(dock)
    _rtimer.timeout.connect(lambda: (t(), _rtimer.stop()) if _view_menu_done or n[0]>=20 else t())
    _rtimer.start()

def _wire(dock):
    global _wired, _dirty_timer, _widget
    if _wired: return
    if _widget is None: _widget = TabPanelWidget(dock)
    def _cc():
        if not _widget or _widget._syncing: return
        if not _widget._self_chg:
            try: _widget.tree.clearSelection()
            except: pass
        _widget._upd(); _widget.sched()
    _handlers["current_changed"] = lambda *_: _cc()
    dock.tabs.currentChanged.connect(_handlers["current_changed"])
    _handlers["tab_close"] = lambda *_: QTimer.singleShot(0, _widget.refresh)
    dock.tabs.tabCloseRequested.connect(_handlers["tab_close"])
    try:
        _tm = QTimer(); _tm.setSingleShot(True); _tm.setInterval(100)
        def _tmf():
            if _widget: _widget._syncing=False; _widget._sig=None; _widget.refresh()
        _tm.timeout.connect(_tmf)
        def _otm(*_):
            if not _widget or _widget._syncing: return
            _widget._syncing=True; _tm.start()
        _handlers["tabs_moved"]=_otm
        dock.tabs.tabBar().tabMoved.connect(_handlers["tabs_moved"])
    except: pass
    proj = QgsProject.instance()
    _handlers["read_project"] = lambda *_: (_widget.load_pfavs(), _widget.refresh())
    proj.readProject.connect(_handlers["read_project"])
    _handlers["write_project"] = lambda *_: _widget.save_pfavs()
    proj.writeProject.connect(_handlers["write_project"])
    try:
        _handlers["clear_project"] = lambda *_: (setattr(_widget,"_pfavs",[]), _widget.refresh())
        proj.cleared.connect(_handlers["clear_project"])
    except: pass
    if _dirty_timer is None:
        _dirty_timer = QTimer(_widget); _dirty_timer.setInterval(500); _dirty_timer.timeout.connect(_widget._upd)
    if not _dirty_timer.isActive(): _dirty_timer.start()
    _wired = True

def _unwire(dock):
    global _wired
    if not _wired: return
    if _dirty_timer:
        try: _dirty_timer.stop()
        except: pass
    if _alive(dock):
        for k,sig in [("current_changed",dock.tabs.currentChanged),("tab_close",dock.tabs.tabCloseRequested)]:
            try:
                if _handlers[k]: sig.disconnect(_handlers[k])
            except: pass
        try:
            if _handlers["tabs_moved"]: dock.tabs.tabBar().tabMoved.disconnect(_handlers["tabs_moved"])
        except: pass
    proj = QgsProject.instance()
    for k,sig in [("read_project",proj.readProject),("write_project",proj.writeProject)]:
        try:
            if _handlers[k]: sig.disconnect(_handlers[k])
        except: pass
    try:
        if _handlers["clear_project"]: proj.cleared.disconnect(_handlers["clear_project"])
    except: pass
    for k in _handlers: _handlers[k]=None
    _wired = False

def _on_startup(dock):
    global _dock_ref; _dock_ref=dock
    _wire(dock); _try_view(dock); _widget.load_pfavs(); _widget.refresh()

def _on_shutdown(dock):
    global _widget, _dirty_timer
    _unwire(dock); _dirty_timer=None; _widget=None

def _on_enable(dock):
    global _dock_ref; _dock_ref=dock; _wire(dock); _try_view(dock)
    if _widget: _widget.load_pfavs(); _widget.refresh()

def _on_disable(dock): _unwire(dock)

def _panel(dock):
    global _widget
    if _widget is None: _widget = TabPanelWidget(dock)
    return {"id":"FileTabplus","title":"Tabs","widget":_widget,"area":"left"}

def _on_file_opened(d,p,path):
    if _widget: _widget.push_recent(path); _widget.refresh()
def _on_file_saved(d,p,path):
    if _widget: _widget._upd()
def _on_tab_changed(d,p):
    if _widget: _widget._upd(); _widget.sched()

def _settings_dialog(dock):
    if not _widget: return
    try: p=dock.iface.mainWindow()
    except: p=dock
    d=_SettingsDialog(_widget,p); d.setModal(True); d.show(); d.raise_(); d.exec_()

def register():
    return {"id":"FileTabplus","name":"FileTab+ v"+__version__,
        "description":"FileTab+: tabs, favs, recents, drag-reorder.",
        "core":True,"builtin":True,
        "hooks":{"on_startup":_on_startup,"on_shutdown":_on_shutdown,
            "on_enable":_on_enable,"on_disable":_on_disable,
            "panel":_panel,"on_file_opened":_on_file_opened,
            "on_file_saved":_on_file_saved,"on_tab_changed":_on_tab_changed,
            "settings_dialog":_settings_dialog}}
