"""A real series/episode tree with one selection source shared by checkboxes."""
from pathlib import Path
from PySide6.QtCore import QAbstractItemModel,QModelIndex,Qt,Signal
from PySide6.QtGui import QColor
from series_policy import series_key,effective_roi

STATUS={'pending':'等待处理','running':'处理中','paused':'已暂停','done':'已导出','failed':'失败 · 可重试','interrupted':'已停止 · 可继续','pausing':'正在暂停','stopping':'正在保存并停止'}
LANGUAGE_NAMES={'en-US':'英语','zh-Hans':'简体中文','zh-Hant':'繁體中文','ja-JP':'日本語','ko-KR':'韩语','es-ES':'西班牙语','fr-FR':'法语','de-DE':'德语','pt-BR':'葡萄牙语','it-IT':'意大利语'}

def _language_status(job):
    values=job.get('resolved_languages') or job.get('detected_language')
    if not values:return ''
    if isinstance(values,str):values=[values]
    names='、'.join(LANGUAGE_NAMES.get(value,value) for value in values if value != 'auto')
    return f' · 识别为{names}' if names else ''
class QueueModel(QAbstractItemModel):
    checked=Signal(object,bool)
    HEADERS=['剧集 / 视频文件','字幕区域','状态']
    def __init__(self,jobs,regions=None,auto_region_groups=None):
        super().__init__();self.jobs=jobs;self.regions=regions if regions is not None else {};self.auto_region_groups=auto_region_groups if auto_region_groups is not None else set();self.groups=[];self.selected=set();self.rebuild()
    def rebuild(self):
        self.groups=[];lookup={}
        for j in self.jobs:
            key=series_key(j)
            if key not in lookup:
                group={'series':key,'children':[]};lookup[key]=group;self.groups.append(group)
            lookup[key]['children'].append(j)
    def refresh(self):
        existing=[(g['series'],[(j['id'],id(j)) for j in g['children']]) for g in self.groups]
        desired=[];lookup={}
        for j in self.jobs:
            k=series_key(j)
            if k not in lookup:lookup[k]=[];desired.append((k,lookup[k]))
            lookup[k].append((j['id'],id(j)))
        if existing==desired:self.notify();return False
        self.beginResetModel();self.rebuild();self.endResetModel();return True
    def notify(self,ids=None,roles=None):
        roles=roles or [Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.CheckStateRole,Qt.ItemDataRole.ToolTipRole,Qt.ItemDataRole.ForegroundRole]
        for gi,g in enumerate(self.groups):
            parent=self.index(gi,0)
            if ids is not None and not any(j['id'] in ids for j in g['children']):continue
            self.dataChanged.emit(parent,self.index(gi,2),roles)
            if g['children']:self.dataChanged.emit(self.index(0,0,parent),self.index(len(g['children'])-1,2,parent),roles)
    def set_selected(self,ids):
        ids=set(ids)
        if ids==self.selected:return
        self.selected=ids;self.notify(roles=[Qt.ItemDataRole.CheckStateRole])
    def columnCount(self,parent=QModelIndex()):return 3
    def rowCount(self,parent=QModelIndex()):
        if not parent.isValid():return len(self.groups)
        node=parent.internalPointer()
        return len(node['children']) if parent.column()==0 and 'children' in node else 0
    def index(self,row,col,parent=QModelIndex()):
        if not self.hasIndex(row,col,parent):return QModelIndex()
        nodes=self.groups if not parent.isValid() else parent.internalPointer()['children']
        return self.createIndex(row,col,nodes[row])
    def parent(self,index):
        if not index.isValid():return QModelIndex()
        node=index.internalPointer()
        if 'children' in node:return QModelIndex()
        for i,g in enumerate(self.groups):
            if any(j is node for j in g['children']):return self.createIndex(i,0,g)
        return QModelIndex()
    def jobs_at(self,index):
        if not index.isValid():return []
        n=index.internalPointer();return n['children'] if 'children' in n else [n]
    def indexes_for(self,ids):
        for gi,g in enumerate(self.groups):
            parent=self.index(gi,0)
            for ji,j in enumerate(g['children']):
                if j['id'] in ids:yield self.index(ji,0,parent)
    def flags(self,index):
        flags=super().flags(index)
        if index.column()==0:flags|=Qt.ItemFlag.ItemIsUserCheckable
        return flags
    def headerData(self,s,o,r=Qt.ItemDataRole.DisplayRole):
        if o==Qt.Orientation.Horizontal and r==Qt.ItemDataRole.DisplayRole:return self.HEADERS[s]
    def setData(self,index,value,role=Qt.ItemDataRole.EditRole):
        if role!=Qt.ItemDataRole.CheckStateRole:return False
        self.checked.emit([j['id'] for j in self.jobs_at(index)],value==Qt.CheckState.Checked.value or value==Qt.CheckState.Checked);return True
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():return None
        node=index.internalPointer();group='children' in node;jobs=self.jobs_at(index)
        if role==Qt.ItemDataRole.CheckStateRole and index.column()==0:
            n=sum(j['id'] in self.selected for j in jobs)
            return Qt.CheckState.Checked if n==len(jobs) else Qt.CheckState.PartiallyChecked if n else Qt.CheckState.Unchecked
        if role==Qt.ItemDataRole.ToolTipRole:return node['series'] if group else node.get('error') or '\n'.join(filter(None,[node['source'],'原视频已移动；使用“更多操作 → 重新定位视频文件”找回。' if node.get('source_missing') else '',node.get('phase','')]))
        if role==Qt.ItemDataRole.DisplayRole:
            if group:
                done=sum(j['status']=='done' for j in jobs);active=next((j for j in jobs if j['status'] in {'running','paused','pausing','stopping'}),None)
                status=f'{done}/{len(jobs)} 已导出'
                if active:status+=' · '+STATUS.get(active['status'],active['status'])+_language_status(active)
                return [Path(node['series']).name+' · '+str(len(jobs))+' 集','',status][index.column()]
            status=STATUS.get(node['status'],node['status'])+(' · 设置已变' if node.get('settings_changed') and node['status']=='done' else '')
            if node['status']=='pending' and node.get('pending_reason'):status+=' · '+node['pending_reason']
            if node['status']=='running':
                if node.get('work_fraction') is not None:status+=f" · {min(99,int(100*node['work_fraction']))}%"
                elif node.get('duration') and node.get('processed_seconds') is not None:status+=f" · {min(99,int(100*node['processed_seconds']/node['duration']))}%"
                if node.get('phase'):status+=' · '+node['phase']
            status += _language_status(node)
            if node.get('source_missing'):status+=' · 原视频待定位'
            if node.get('language_phase') and not node.get('resolved_languages'):status+=' · '+node['language_phase']
            region=('本集单独区域' if node.get('roi_override') else
                    '整剧共用区域' if effective_roi(node,self.regions) or node.get('detected_roi') else
                    '自动定位' if series_key(node) in self.auto_region_groups else '待框选')
            return [Path(node['source']).name,region,status][index.column()]
        if role==Qt.ItemDataRole.ForegroundRole and index.column()==2 and not group:
            return QColor('#9c3030' if node['status']=='failed' else '#126b5e' if node['status']=='done' else '#596762')
