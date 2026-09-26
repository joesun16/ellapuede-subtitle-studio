import os,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from ella_app import MainWindow,STYLE
APP=QApplication.instance() or QApplication([]);APP.setStyleSheet(STYLE)
class ProjectUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.w=MainWindow(Path(self.tmp.name));self.w.show()
        self.w.jobs.extend([{'id':str(i),'source':f'/{g}/{i}.mp4','relative':f'{g}/{i}.mp4','series':g,'status':'done' if i==0 else 'pending','roi':None,'duration':60,'settings':dict(self.w.defaults)} for i,g in enumerate(('A','A','B'))]);self.w.refresh_queue();APP.processEvents()
    def tearDown(self):self.w.close();self.w.deleteLater();APP.processEvents();self.tmp.cleanup()
    def test_context_help_is_compact_aligned_and_idle_status_is_hidden(self):
        icons=(self.w.selection_info,self.w.scope_info,self.w.language_info,self.w.mode_info,self.w.progress_info)
        self.assertEqual({(icon.width(),icon.height()) for icon in icons},{(22,22)})
        self.assertTrue(all(icon.isVisible() and icon.toolTip() for icon in icons[1:]))
        self.assertFalse(self.w.task_actions_panel.isVisible())
        self.w.queue_table.selectRow(0);APP.processEvents()
        self.assertTrue(self.w.selection_info.isVisible())
        self.assertFalse(self.w.language_hint.isVisible())
        self.assertFalse(self.w.mode_note.isVisible())
        self.assertFalse(self.w.statusBar().isVisible())
        self.w.language.setCurrentIndex(self.w.language.findData('ko-KR'))
        self.assertIn('韩语',self.w.language_info.toolTip())
        self.w.show_status('已完成操作');APP.processEvents()
        self.assertTrue(self.w.statusBar().isVisible())
        self.w.statusBar().clearMessage();APP.processEvents()
        self.assertFalse(self.w.statusBar().isVisible())
    def test_workspace_switches_between_import_and_queue_without_ghost_actions(self):
        self.assertIs(self.w.queue_stack.currentWidget(),self.w.queue_table)
        self.assertFalse(self.w.task_actions_panel.isVisible())
        self.w.queue_table.selectRow(0);APP.processEvents()
        self.assertTrue(self.w.task_actions_panel.isVisible())
        self.w.jobs.clear();self.w.selected_ids.clear();self.w.refresh_queue();APP.processEvents()
        self.assertIs(self.w.queue_stack.currentWidget(),self.w.empty_state)
        self.assertFalse(self.w.task_actions_panel.isVisible())
        self.assertFalse(self.w.more_btn.isVisible())
    def test_group_checkbox_selection_and_undo(self):
        self.w.queue_table.selectRow(0);self.assertEqual(len(self.w.selected_jobs()),2)
        self.w.set_checked(['1'],False);self.assertEqual([j['id'] for j in self.w.selected_jobs()],['0'])
        self.w.remove_selected();self.assertEqual(len(self.w.jobs),2);self.w.undo_remove();self.assertEqual(len(self.w.jobs),3)
    def test_cross_series_region_never_opens_first_video_editor(self):
        self.w.select_all_tasks()
        with patch('ella_app.CropDialog') as crop,patch.object(self.w,'show_error') as error:self.w.set_roi();crop.assert_not_called();error.assert_called_once()
    def test_selected_series_settings_only_change_that_series(self):
        self.w.queue_table.selectRow(0);self.w.language.setCurrentIndex(self.w.language.findData('ko-KR'))
        self.assertEqual(self.w.jobs[0]['status'],'pending');self.assertEqual(self.w.jobs[0]['settings']['language'],'ko-KR');self.assertEqual(self.w.jobs[2]['settings']['language'],'auto')
    def test_defaults_remain_editable_with_selected_tasks(self):
        self.w.queue_table.selectRow(0);self.w.settings_scope.setCurrentIndex(0);self.w.language.setCurrentIndex(self.w.language.findData('ko-KR'))
        self.assertEqual(self.w.defaults['language'],'ko-KR');self.assertEqual(self.w.jobs[0]['settings']['language'],'auto');self.assertIsNone(self.w.settings_scope.currentData())
    def test_one_series_language_choice_changes_the_task_even_with_default_scope_visible(self):
        self.w.jobs.pop();self.w.refresh_queue();self.w.queue_table.clearSelection()
        self.w.settings_scope.setCurrentIndex(0)
        self.w.language.setCurrentIndex(self.w.language.findData('en-US'))
        self.assertEqual(self.w.settings_scope.currentData(),'A')
        self.assertEqual([j['settings']['language'] for j in self.w.jobs],['en-US','en-US'])
    def test_changed_export_format_reexports_without_missing_video_or_ocr(self):
        import json,time
        from PySide6.QtTest import QTest
        from workspace_policy import apply_settings
        job=self.w.jobs[0];self.w.jobs[:]=[job]
        stem=Path(self.tmp.name)/'result';Path(str(stem)+'.subtitles.json').write_text(json.dumps({
            'video':{'width':640,'height':360,'duration':2},
            'events':[{'id':1,'start':.1,'end':1.5,'text':'Hello'}]}))
        job['result_stem']=str(stem);job['settings']=dict(self.w.defaults,format='srt',output=self.tmp.name)
        apply_settings([job],{'format':'ass'},'A');self.w.output.setText(self.tmp.name);self.w.refresh_queue()
        with patch('subtitle_ocr.VisionPool',side_effect=AssertionError('OCR must not run')):
            self.w.start_queue()
            deadline=time.monotonic()+3
            while job['status']!='done' and time.monotonic()<deadline:QTest.qWait(10)
        self.assertEqual(job['status'],'done')
        self.assertTrue((Path(self.tmp.name)/'A'/'0.ass').exists())
    def test_old_completed_job_with_changed_language_is_not_shown_as_exported(self):
        import json
        state=Path(self.tmp.name)/'legacy';state.mkdir()
        (state/'workspace.json').write_text(json.dumps({'defaults':dict(self.w.defaults,language='ko-KR'),
            'jobs':[{'id':'old','series':'Drama','source':'/missing/episode.mp4','relative':'episode.mp4',
                     'status':'done','settings_changed':True,'settings':dict(self.w.defaults,language='en-US')}]}))
        other=MainWindow(state)
        self.assertEqual(other.defaults['language'],'auto')
        self.assertEqual(other.jobs[0]['status'],'pending')
        self.assertEqual(other.language.currentData(),'en-US')
        other.close()

    def test_checkbox_selection_keeps_settings_scope_in_sync(self):
        self.w.select_all_tasks();self.w.set_checked(['2'],False)
        self.assertEqual(self.w.settings_scope.currentData(),'A')
        self.w.set_checked(['2'],True)
        self.assertIsNone(self.w.settings_scope.currentData())

    def test_resolved_language_is_visible_without_replacing_auto_setting(self):
        self.w.queue_table.selectRow(0);self.w.active=self.w.jobs[0]
        self.w.handle_event({'type':'language','requested':['auto'],'resolved':['ko-KR'],'detected':'ko-KR'})
        self.assertEqual(self.w.jobs[0]['settings']['language'],'auto')
        self.assertIn('韩语',self.w.language_hint.text())
        index=self.w.queue_model.index(0,2,self.w.queue_model.index(0,0))
        self.assertIn('识别为韩语',self.w.queue_model.data(index))
        self.w.active=None
    def test_active_job_protected_waiting_jobs_removable(self):
        self.w.active=self.w.jobs[1];self.w.running=True;self.w.select_all_tasks()
        self.assertFalse(self.w.remove_btn.isEnabled())
        self.w.remove_selected();self.assertEqual(len(self.w.jobs),3)
        self.w.set_checked(['1'],False);self.assertTrue(self.w.remove_btn.isEnabled())
        self.w.remove_selected();self.assertEqual([j['id'] for j in self.w.jobs],['1'])
        self.w.active=None;self.w.running=False
    def test_reprocess_is_visible_and_restarts_the_active_job(self):
        import time
        job=self.w.jobs[1];job['status']='running';self.w.active=job;self.w.job_started=time.monotonic()
        self.w.control_dir=Path(self.tmp.name)/'controls'/job['id'];self.w.control_dir.mkdir(parents=True)
        self.w.process=object();self.w.set_running_ui(True);self.w.set_checked([job['id']],True)
        self.assertTrue(self.w.reprocess_btn.isEnabled())
        self.assertEqual(self.w.reprocess_btn.text(),'停止并重做本集')
        with patch.object(self.w,'start_next'):
            self.w.reprocess_btn.click()
            self.assertTrue((self.w.control_dir/'stop').exists())
            self.w.complete_job(130)
        self.assertEqual(job['status'],'pending')
        self.assertTrue(job['replace_output'])
        self.assertNotIn('error',job)
        self.w.process=None;self.w.set_running_ui(False)
    def test_reprocess_other_completed_job_during_batch(self):
        active=self.w.jobs[1];active['status']='running';self.w.active=active;self.w.set_running_ui(True)
        self.w.set_checked([self.w.jobs[0]['id']],True);self.w.reprocess_btn.click()
        self.assertEqual(self.w.jobs[0]['status'],'pending')
        self.assertIs(self.w.active,active)
        self.w.active=None;self.w.set_running_ui(False)
    def test_overall_progress_survives_starting_next_episode(self):
        self.w.active=self.w.jobs[1];self.w.job_started=__import__('time').monotonic();self.w.handle_event({'type':'progress','seconds':30,'duration':60})
        self.assertEqual(self.w.progress.value(),480);self.w.handle_event({'type':'phase','phase':'准备下一集'});self.assertEqual(self.w.progress.value(),480)
        self.w.save_state();other=MainWindow(Path(self.tmp.name));self.assertEqual(other.jobs[1]['processed_seconds'],30);other.close();self.w.active=None
    def test_relocating_auto_region_resets_previous_progress(self):
        self.w.jobs[0]['processed_seconds']=60
        self.w.queue_table.selectRow(0);self.w.clear_roi()
        self.assertEqual(self.w.jobs[0]['processed_seconds'],0)
        self.assertEqual(self.w.jobs[0]['status'],'pending')

    def test_real_checkbox_click_keeps_other_selections_and_scroll_model(self):
        from PySide6.QtCore import Qt,QPersistentModelIndex
        from PySide6.QtWidgets import QStyleOptionViewItem,QStyle
        from PySide6.QtTest import QTest,QSignalSpy
        self.w.select_all_tasks();model=self.w.queue_model;parent=model.index(0,0);idx=model.index(1,0,parent);persistent=QPersistentModelIndex(idx);reset=QSignalSpy(model.modelReset)
        option=QStyleOptionViewItem();self.w.queue_table.itemDelegateForIndex(idx).initStyleOption(option,idx);option.rect=self.w.queue_table.visualRect(idx)
        rect=self.w.queue_table.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator,option,self.w.queue_table)
        QTest.mouseClick(self.w.queue_table.viewport(),Qt.MouseButton.LeftButton,pos=rect.center());APP.processEvents()
        self.assertEqual(self.w.selected_ids,{'0','2'});self.assertEqual(model.data(idx,Qt.ItemDataRole.CheckStateRole),Qt.CheckState.Unchecked)
        self.assertEqual(model.data(parent,Qt.ItemDataRole.CheckStateRole),Qt.CheckState.PartiallyChecked);self.assertEqual(reset.count(),0);self.assertTrue(persistent.isValid())
    def test_progress_and_region_emit_model_updates_without_resetting_selection(self):
        from PySide6.QtCore import Qt,QPersistentModelIndex
        from PySide6.QtTest import QSignalSpy
        self.w.select_all_tasks();self.w.active=self.w.jobs[1];self.w.active['status']='running';self.w.job_started=__import__('time').monotonic()
        model=self.w.queue_model;idx=model.index(1,2,model.index(0,0));persistent=QPersistentModelIndex(idx);changed=QSignalSpy(model.dataChanged);reset=QSignalSpy(model.modelReset)
        self.w.handle_event({'type':'progress','seconds':15,'duration':60});self.w.handle_event({'type':'phase','phase':'自动核验画面'});self.w.handle_event({'type':'region','roi':[.1,.6,.9,.8],'automatic':True})
        self.assertIn('26%',model.data(idx));self.assertIn('自动核验画面',model.data(idx));self.assertGreater(changed.count(),0);self.assertEqual(reset.count(),0)
        self.assertEqual(self.w.selected_ids,{'0','1','2'});self.assertTrue(persistent.isValid());self.w.active=None

    def test_manual_region_is_required_unless_auto_is_explicit(self):
        self.w.queue_table.clearSelection()
        self.w.output.setText(self.tmp.name)
        for job in self.w.jobs:
            source=Path(self.tmp.name)/f'{job["id"]}.mp4';source.touch();job['source']=str(source)
        with patch.object(self.w,'set_roi',return_value=False) as choose:
            self.w.start_queue()
            choose.assert_called_once_with(target=self.w.jobs[1])
            self.assertFalse(self.w.running)
        self.w.auto_region_groups.add('A');self.w.auto_region_groups.add('B')
        with patch.object(self.w,'set_roi') as choose,patch.object(self.w,'start_next'):
            self.w.start_queue();choose.assert_not_called();self.assertTrue(self.w.running)
        self.w.set_running_ui(False)

    def test_refine_progress_is_project_progress_not_scan_completion(self):
        self.w.active=self.w.jobs[1];self.w.active['status']='running';self.w.job_started=__import__('time').monotonic()
        self.w.handle_event({'type':'progress','seconds':60,'duration':60})
        self.assertEqual(self.w.progress.value(),600)
        self.w.handle_event({'type':'verify_progress','done':5,'total':10})
        self.assertEqual(self.w.progress.value(),630)
        self.assertIn('复核画面 5/10',self.w.phase_label.text())
        self.w.active=None

    def test_stop_status_is_not_overwritten_by_inflight_worker_events(self):
        self.w.active=self.w.jobs[1];self.w.active['status']='stopping';self.w.stopping=True;self.w.paused=False
        self.w.phase_label.setText('正在保存进度并停止…')
        self.w.handle_event({'type':'phase','phase':'自动核验画面'})
        self.w.handle_event({'type':'paused'});self.w.handle_event({'type':'resumed'})
        self.assertEqual(self.w.active['status'],'stopping')
        self.assertEqual(self.w.phase_label.text(),'正在保存进度并停止…')
        self.w.active=None;self.w.handle_event({'type':'error','message':'late error'})
