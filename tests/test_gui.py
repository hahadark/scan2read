import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from scan2read.gui import Application, app_root, dpi_scale, parse_dropped_paths, pdfs_from_inputs


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.settings_path=Path(self.temp.name)/'settings.json'
        self.settings_patch=patch.object(Application,'_settings_path',return_value=self.settings_path)
        self.settings_patch.start()
        self.threads=patch('scan2read.gui.threading.Thread');self.threads.start()
        self.root=tk.Tk();self.root.withdraw()
        self.app=Application(self.root)

    def tearDown(self):
        self.app.active={};self.app.gpu_process=None
        self.app.close()
        self.threads.stop();self.settings_patch.stop();self.temp.cleanup()

    def add(self,*names):
        paths=[]
        for name in names:
            path=Path(self.temp.name)/name
            path.parent.mkdir(parents=True,exist_ok=True);path.touch();paths.append(str(path.resolve()))
        self.app._set_sources(paths)
        return paths

    def _complete_active(self,code=0):
        """Finish every currently-active job with `code` and process the resulting events."""
        for key in list(self.app.active.keys()):
            self.app.events.put(('done',(key,code)))
        self.app.poll()

    def test_adds_files_to_visible_list_and_deduplicates(self):
        paths=self.add('a.pdf','b.pdf')
        self.app._set_sources([paths[0]])
        self.assertEqual(self.app.queue,paths)
        self.assertEqual(len(self.app.file_list.get_children()),2)
        self.assertIn('a.pdf',self.app.file_list.item('0')['values'][0])
        self.app.file_list.selection_set('0');self.app.remove_selected()
        self.assertEqual(self.app.queue,[paths[1]])
        self.app.clear_sources();self.assertEqual(self.app.queue,[])

    def test_dropped_folder_adds_direct_pdf_files_in_name_order(self):
        folder=Path(self.temp.name)/'books';folder.mkdir()
        nested=folder/'nested';nested.mkdir()
        for path in (folder/'B.pdf',folder/'a.PDF',folder/'notes.txt',nested/'hidden.pdf'):
            path.touch()
        self.app._on_drop(Mock(data=f'{{{folder}}}'))
        self.assertEqual([Path(path).name for path in self.app.queue],['a.PDF','B.pdf'])
        self.assertEqual(len(self.app.file_list.get_children()),2)
        self.assertIn('2개를 추가',self.app.status.get())

    def test_drop_mixes_folder_and_pdf_and_deduplicates(self):
        folder=Path(self.temp.name)/'books';folder.mkdir()
        inside=folder/'inside.pdf';inside.touch()
        outside=Path(self.temp.name)/'outside.pdf';outside.touch()
        data=f'{{{folder}}} {{{outside}}} {{{inside}}}'
        self.app._on_drop(Mock(data=data))
        self.assertEqual(self.app.queue,[str(inside.resolve()),str(outside.resolve())])

    def test_empty_dropped_folder_shows_error(self):
        folder=Path(self.temp.name)/'empty';folder.mkdir()
        with patch('scan2read.gui.messagebox.showerror') as error:
            self.app._on_drop(Mock(data=f'{{{folder}}}'))
        error.assert_called_once()
        self.assertEqual(self.app.queue,[])

    def test_folder_button_adds_pdfs_and_reports_empty_folder(self):
        folder=Path(self.temp.name)/'books';folder.mkdir()
        pdf=folder/'book.pdf';pdf.touch()
        with patch('scan2read.gui.filedialog.askdirectory',return_value=str(folder)):
            self.app.choose_source_folder()
        self.assertEqual(self.app.queue,[str(pdf.resolve())])
        self.app.clear_sources();pdf.unlink()
        with patch('scan2read.gui.filedialog.askdirectory',return_value=str(folder)), \
             patch('scan2read.gui.messagebox.showinfo') as info:
            self.app.choose_source_folder()
        info.assert_called_once()

    def test_pdf_input_expansion_ignores_non_pdf_and_subfolders(self):
        folder=Path(self.temp.name)/'folder';folder.mkdir()
        pdf=folder/'one.pdf';pdf.touch()
        text=folder/'one.txt';text.touch()
        nested=folder/'nested';nested.mkdir();(nested/'two.pdf').touch()
        self.assertEqual(pdfs_from_inputs([str(folder),str(text)]),[str(pdf.resolve())])

    def test_directory_dialog_never_requests_filename(self):
        with patch('scan2read.gui.filedialog.askdirectory',return_value=self.temp.name) as directory, patch('scan2read.gui.filedialog.asksaveasfilename') as file:
            self.app.choose_output()
        directory.assert_called_once();file.assert_not_called()
        self.assertEqual(self.app.output_dir.get(),self.temp.name)

    def test_output_preview_and_commands_share_naming_rule(self):
        paths=self.add('a.pdf','b.pdf')
        self.app.max_parallel_conversions.set('1')  # exercise strictly-sequential naming, not concurrency
        folder=Path(self.temp.name)/'results'
        self.app.output_dir.set(str(folder));self.app.name_rule.set('{index:03d}_{name}_듣기')
        self.assertIn('001_a_듣기.epub',self.app.file_list.item('0')['values'][1])
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))) as popen:
            self.app.start()
            first=popen.call_args.args[0]
            self.assertEqual(first[first.index('--output')+1],str(folder/'001_a_듣기.epub'))
            self._complete_active()
            second=popen.call_args.args[0]
            self.assertEqual(second[second.index('--output')+1],str(folder/'002_b_듣기.epub'))
            self._complete_active()
        self.assertFalse(self.app.in_batch)
        self.assertEqual(self.app.queue,paths)
        self.assertEqual(self.app.file_list.set('0','state'),'완료')
        self.assertIn('2개 성공',self.app.status.get())

    def test_failure_continues_and_stop_retains_file_list(self):
        paths=self.add('a.pdf','b.pdf','c.pdf')
        self.app.max_parallel_conversions.set('1')  # one file fails, then cancel -- exercise in strict sequence
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))) as popen:
            self.app.start();self._complete_active(code=1)
            self.assertEqual(popen.call_count,2)
            self.app.stop();self._complete_active(code=1)
            self.assertEqual(popen.call_count,2)
        self.assertEqual(self.app.queue,paths)
        self.assertEqual([self.app.file_list.set(str(i),'state') for i in range(3)],['실패','중단','취소'])

    def test_settings_saved_and_restored_including_gpu_preference(self):
        self.app.output_dir.set(self.temp.name);self.app.name_rule.set('{name}_tts')
        self.app.columns.set('2단');self.app.spacing.set(False)
        self.app.page_range.set('3-8');self.app.remove_footnotes.set(True)
        self.app.remove_parentheses.set(True);self.app.ignore_text_layer.set(True);self.app.use_gpu.set(False)
        self.app._save_settings()
        self.app.events.put(('gpu-status',{'gpu_name':'NVIDIA test','installed':True}));self.app.poll()
        self.assertFalse(self.app.use_gpu.get())
        from scan2read.project.batch import Preferences
        saved=Preferences.load(self.settings_path)
        self.assertEqual(saved.output_dir,self.temp.name)
        self.assertEqual(saved.name_rule,'{name}_tts')
        self.assertFalse(saved.spacing);self.assertTrue(saved.remove_footnotes)
        self.assertEqual(saved.page_range,'3-8');self.assertFalse(saved.use_gpu)

    def test_flags_and_page_range_apply_to_batch(self):
        self.add('a.pdf','b.pdf')
        self.app.max_parallel_conversions.set('1')  # check each file's flags in strict sequence
        self.app.page_range.set('3-8');self.app.ignore_text_layer.set(True)
        self.app.remove_footnotes.set(True);self.app.remove_parentheses.set(True)
        self.app.gpu_installed=True;self.app.use_gpu.set(True)
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))) as popen:
            self.app.start()
            for _ in range(2):
                command=popen.call_args.args[0]
                for flag in ('--spacing','--reconstruct','--remove-footnotes','--remove-parentheses','--gpu'):self.assertIn(flag,command)
                self.assertEqual(command[command.index('--pages')+1],'3-8')
                self.assertEqual(command[command.index('--text-layer')+1],'off')
                self._complete_active()

    def test_known_page_count_splits_into_ocr_chunks_up_to_max_parallel(self):
        path=self.add('a.pdf')[0]
        self.app.page_counts[path]=40  # default max_parallel=2, MIN_CHUNK_PAGES=15 -> 2 chunks
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))) as popen:
            self.app.start()
            self.assertEqual(popen.call_count,2)
            commands=[call.args[0] for call in popen.call_args_list]
            self.assertTrue(all('ocr-pages' in command for command in commands))
            ranges=sorted(command[command.index('--pages')+1] for command in commands)
            self.assertEqual(ranges,['1-20','21-40'])
            self.assertEqual(len(self.app.active),2)

    def test_max_parallel_one_never_splits_into_chunks(self):
        path=self.add('a.pdf')[0]
        self.app.page_counts[path]=40
        self.app.max_parallel_conversions.set('1')
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))) as popen:
            self.app.start()
            self.assertEqual(popen.call_count,1)
            self.assertIn('convert',popen.call_args.args[0])

    def test_finishing_all_ocr_chunks_launches_finalize(self):
        path=self.add('a.pdf')[0]
        self.app.page_counts[path]=40
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))) as popen:
            self.app.start()
            self.assertEqual(popen.call_count,2)
            self._complete_active()
            self.assertEqual(popen.call_count,3)
            finalize_command=popen.call_args.args[0]
            self.assertIn('convert',finalize_command)
            self._complete_active()
        self.assertEqual(self.app.file_list.set('0','state'),'완료')
        self.assertFalse(self.app.in_batch)

    def test_row_shows_aggregated_chunk_progress(self):
        path=self.add('a.pdf')[0]
        self.app.page_counts[path]=40
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))):
            self.app.start()
            first_chunk_key=next(key for key in self.app.active if self.app.active[key]['job']['range'][0]==1)
            self.app.events.put(('log',(first_chunk_key,'Rendering/OCR: 10 / 40\n')))
            self.app.poll()
        self.assertEqual(self.app.file_list.set('0','state'),'OCR 10/40쪽')

    def test_chunks_and_finalize_share_the_slot_pool_across_files(self):
        paths=self.add('a.pdf','b.pdf')
        self.app.page_counts[paths[0]]=40  # splits into 2 ocr chunks
        self.app.page_counts[paths[1]]=10  # too small to split -> single finalize job
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))) as popen:
            self.app.start()
            # both slots are taken by a's two OCR chunks; b's finalize waits queued
            self.assertEqual(popen.call_count,2)
            self.assertEqual([job['file'] for job in self.app.job_queue],[paths[1]])
            first_a_key=next(key for key in self.app.active if key[0]==paths[0])
            self.app.events.put(('done',(first_a_key,0)))
            self.app.poll()
            # freeing one of a's slots lets b's finalize start immediately
            self.assertEqual(popen.call_count,3)
            self.assertIn('convert',popen.call_args.args[0])
            self.assertEqual(self.app.job_queue,[])

    def test_stop_terminates_every_active_process(self):
        paths=self.add('a.pdf','b.pdf')
        self.app.page_counts[paths[0]]=40
        with patch('scan2read.gui.subprocess.Popen',side_effect=lambda *a,**k:Mock(stdout=iter([]))):
            self.app.start()
            self.assertEqual(len(self.app.active),2)
            processes=[entry['process'] for entry in self.app.active.values()]
            self.app.stop()
            for process in processes:process.terminate.assert_called_once()
            self.assertTrue(self.app.cancelled)

    def test_cancel_waits_for_a_files_last_active_job_before_marking_it_aborted(self):
        path=self.add('a.pdf')[0]
        self.app.page_counts[path]=40
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))):
            self.app.start()
            self.app.stop()
            keys=list(self.app.active.keys())
            self.assertEqual(len(keys),2)
            self.app.events.put(('done',(keys[0],1)))
            self.app.poll()
            # one of two active chunks ended -- not aborted yet, batch still running
            self.assertNotEqual(self.app.file_list.set('0','state'),'중단')
            self.assertTrue(self.app.in_batch)
            self.app.events.put(('done',(keys[1],1)))
            self.app.poll()
            self.assertEqual(self.app.file_list.set('0','state'),'중단')
            self.assertFalse(self.app.in_batch)

    def test_max_parallel_persisted_and_validated(self):
        self.app.max_parallel_conversions.set('3')
        self.app._save_settings()
        from scan2read.project.batch import Preferences
        saved=Preferences.load(self.settings_path)
        self.assertEqual(saved.max_parallel_conversions,'3')
        self.add('a.pdf')
        self.app.max_parallel_conversions.set('9')
        with patch('scan2read.gui.messagebox.showerror') as error, \
             patch('scan2read.gui.subprocess.Popen') as popen:
            self.app.start();error.assert_called_once();popen.assert_not_called()

    def test_ai_context_flag_and_key_are_passed_only_to_worker_environment(self):
        self.add('a.pdf')
        self.app.use_ai_context.set(True);self.app.api_key.set('sk-test-secret')
        self.app.ai_cost_limit_usd.set('0.75')
        for variable in (self.app.ai_ocr_words,self.app.ai_spacing,self.app.ai_anomalies,
                         self.app.ai_structure,self.app.ai_headings,self.app.ai_glosses):variable.set(True)
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))) as popen:
            self.app.start()
            command=popen.call_args.args[0]
            environment=popen.call_args.kwargs['env']
        self.assertIn('--ai-context',command)
        self.assertEqual(command[command.index('--ai-cost-limit-usd')+1],'0.75')
        for flag in ('--ai-ocr-words','--ai-spacing','--ai-anomalies','--ai-structure','--ai-headings','--ai-glosses'):
            self.assertIn(flag,command)
        self.assertNotIn('sk-test-secret',command)
        self.assertEqual(environment['OPENAI_API_KEY'],'sk-test-secret')
        saved=json.loads(self.settings_path.read_text(encoding='utf-8'))
        self.assertNotIn('api_key',saved)
        self.app.active={};self.app.in_batch=False

    def test_launch_command_includes_provider_and_model_with_matching_env_var(self):
        self.add('a.pdf')
        self.app.use_ai_context.set(True);self.app.ai_anomalies.set(True)
        self.app.ai_provider_display.set('Claude (Anthropic)')
        self.app.ai_model.set('claude-opus-5')
        self.app.api_key.set('claude-secret')
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))) as popen:
            self.app.start()
            command=popen.call_args.args[0]
            environment=popen.call_args.kwargs['env']
        self.assertIn('--ai-provider',command)
        self.assertEqual(command[command.index('--ai-provider')+1],'anthropic')
        self.assertEqual(command[command.index('--ai-model')+1],'claude-opus-5')
        self.assertEqual(environment.get('ANTHROPIC_API_KEY'),'claude-secret')
        self.assertNotIn('OPENAI_API_KEY',environment)
        self.app.active={};self.app.in_batch=False

    def test_switching_provider_reloads_that_providers_own_stored_key(self):
        self.app.ai_provider_display.set('OpenAI')
        self.app.api_key.set('openai-secret');self.app.remember_api_key.set(True)
        self.app._save_credentials()
        self.app.ai_provider_display.set('Claude (Anthropic)')
        self.app.api_key.set('claude-secret')
        self.app._save_credentials()
        self.app.ai_provider_display.set('OpenAI')
        self.assertEqual(self.app.api_key.get(),'openai-secret')
        self.app.ai_provider_display.set('Claude (Anthropic)')
        self.assertEqual(self.app.api_key.get(),'claude-secret')

    def test_model_combo_resets_to_a_valid_choice_when_provider_changes(self):
        self.app.ai_model.set('gpt-5.6-luna')
        self.app.ai_provider_display.set('Gemini (Google)')
        self.assertEqual(self.app.ai_provider.get(),'google')
        self.assertIn(self.app.ai_model.get(),self.app.model_combo['values'])

    def test_unknown_typed_model_warns_registry_model_shows_its_rate(self):
        self.app.ai_provider_display.set('OpenAI')
        self.app.ai_model.set('gpt-5.6-luna')
        known=self.app.model_verified_status.get()
        self.assertIn('0.2',known)
        self.assertNotIn('⚠',known)
        # The model box is free-text, so a typo or a model we don't carry
        # rates for must say so rather than silently costing an unknown amount.
        self.app.ai_model.set('gpt-9-does-not-exist')
        self.assertIn('⚠',self.app.model_verified_status.get())

    def test_switching_provider_selects_that_providers_cheap_default(self):
        self.app.ai_provider_display.set('Claude (Anthropic)')
        self.assertEqual(self.app.ai_model.get(),'claude-sonnet-5')
        self.app.ai_provider_display.set('Gemini (Google)')
        self.assertEqual(self.app.ai_model.get(),'gemini-2.5-flash')

    def test_check_connection_uses_the_selected_provider_and_model(self):
        import scan2read.gui as gui_module
        self.app.ai_provider_display.set('Gemini (Google)')
        self.app.ai_model.set('gemini-2.5-flash')
        self.app.api_key.set('gemini-secret')
        with patch('scan2read.cleanup.ai_providers.check_access') as check:
            self.app.check_api_connection()
            # threading.Thread is mocked class-wide (setUp); run the target
            # it was constructed with synchronously instead of really threading.
            target=gui_module.threading.Thread.call_args.kwargs['target']
            target()
        check.assert_called_once_with('google','gemini-2.5-flash','gemini-secret')

    def test_estimate_and_actual_usage_are_visible(self):
        path=self.add('a.pdf')[0]
        self.app.page_counts[path]=100
        self.app.use_ai_context.set(True);self.app.ai_boundary.set(True)
        for variable in (self.app.ai_ocr_words,self.app.ai_spacing,self.app.ai_anomalies,
                         self.app.ai_structure,self.app.ai_headings):variable.set(False)
        self.app._refresh_ai_estimate()
        self.assertIn('입력 90,000',self.app.ai_estimate_status.get())
        self.app._show_ai_usage(path,{"input_tokens":100,"output_tokens":20,"cost_usd":0.000044,
            "limit_reached":True,"features":{"boundary":{"requests":1,"input_tokens":100,
            "output_tokens":20,"cost_usd":0.000044}}})
        self.assertIn('한도 도달',self.app.ai_usage_status.get())
        self.assertIn('문단 경계 검사',self.app.ai_usage_status.get())

    def test_ai_progress_shows_batch_count_and_eta(self):
        self.app._show_ai_progress({"stage":"ai_enhance","completed_batches":1,"total_batches":3,
            "elapsed_seconds":2.0,"estimated_remaining_seconds":4.0})
        self.assertIn('1/3',self.app.ai_progress_status.get())
        self.assertIn('AI 보정',self.app.ai_progress_status.get())
        self.assertIn('4',self.app.ai_progress_status.get())

    def test_ai_progress_log_line_is_parsed_and_does_not_reach_the_log_widget(self):
        key=('a.pdf','finalize')
        self.app.events.put(('log',(key,'SCAN2READ_AI_PROGRESS {"stage":"ai_context","completed_batches":2,'
                                    '"total_batches":2,"elapsed_seconds":1.0,"estimated_remaining_seconds":null}\n')))
        self.app.poll()
        self.assertIn('2/2',self.app.ai_progress_status.get())
        self.assertIn('문단 경계 검사',self.app.ai_progress_status.get())
        self.assertNotIn('SCAN2READ_AI_PROGRESS',self.app.log.get('1.0','end'))

    def test_invalid_cost_limit_prevents_start(self):
        self.add('a.pdf');self.app.ai_cost_limit_usd.set('-1')
        with patch('scan2read.gui.messagebox.showerror') as error, \
             patch('scan2read.gui.subprocess.Popen') as popen:
            self.app.start();error.assert_called_once();popen.assert_not_called()

    def test_successful_api_check_shows_connected_and_saves_encrypted_key(self):
        self.app.api_key.set('sk-test-secret');self.app.remember_api_key.set(True)
        self.app.events.put(('api-check',(True,'sk-test-secret','GPT-5.6 Luna 연결됨')))
        self.app.poll()
        self.assertEqual(self.app.api_status.get(),'GPT-5.6 Luna 연결됨')
        credential=self.app._credentials_path().read_text(encoding='utf-8')
        self.assertNotIn('sk-test-secret',credential)

    def test_invalid_rule_or_range_prevents_start(self):
        self.add('a.pdf')
        for rule,pages in [('../{name}',''),('{bad}',''),('{name}','5-2')]:
            self.app.name_rule.set(rule);self.app.page_range.set(pages)
            with patch('scan2read.gui.messagebox.showerror') as error,patch('scan2read.gui.subprocess.Popen') as popen:
                self.app.start();error.assert_called_once();popen.assert_not_called()

    def test_stale_inspection_is_ignored(self):
        self.app.source.set('new.pdf')
        self.app.events.put(('text-layer',('old.pdf',{'page_count':10,'pages_with_text_layer':10})))
        self.app.poll();self.assertEqual(self.app.text_layer_status.get(),'')

    def test_changes_blocked_during_conversion(self):
        paths=self.add('a.pdf')
        with patch('scan2read.gui.subprocess.Popen',return_value=Mock(stdout=iter([]))):self.app.start()
        self.app.clear_sources();self.app._set_sources(['b.pdf'])
        self.assertEqual(self.app.queue,paths)
        self.assertTrue(self.app.name_rule.get())
        self.assertEqual(str(self.app.edit_controls[0][0]['state']),'disabled')


    def test_dpi_scale_multiplies_raw_pixel_geometry(self):
        # A second, independent Application at 1.5x -- window/Treeview/
        # wraplength are raw pixels Tk never scales on its own, unlike fonts.
        extra_root=tk.Tk();extra_root.withdraw()
        try:
            scaled=Application(extra_root,dpi_scale=1.5)
            extra_root.update_idletasks()
            self.assertEqual(extra_root.geometry().split('+')[0],'1500x1050')
            self.assertEqual(scaled.file_list.column('source','width'),480)  # 320*1.5
        finally:
            extra_root.destroy()

    def test_default_dpi_scale_leaves_geometry_unscaled(self):
        self.root.update_idletasks()
        self.assertEqual(self.root.geometry().split('+')[0],'1000x700')
        self.assertEqual(self.app.file_list.column('source','width'),320)

    def test_sv_ttk_fonts_are_overridden_to_malgun_gothic(self):
        import scan2read.gui as gui_module
        import tkinter.font as tkfont
        if gui_module.sv_ttk is None:
            self.skipTest("sv_ttk not installed")
        for name in gui_module._SV_TTK_FONTS:
            font = tkfont.Font(root=self.root, name=name, exists=True)
            self.assertEqual(font.actual()["family"], "맑은 고딕", name)

    def test_cancel_terminates_worker(self):
            process = Mock()
            self.app.active = {("a.pdf", "finalize"): {"process": process, "job": {"kind": "finalize", "file": "a.pdf"}}}
            self.app.stop()
            process.terminate.assert_called_once()
            self.assertTrue(self.app.cancelled)

    def test_no_gpu_section_when_no_nvidia_gpu(self):
            self.app.events.put(('gpu-status', {'gpu_name': None, 'installed': False}))
            self.app.poll()
            self.assertEqual(self.app.gpu_frame.winfo_children(), [])

    def test_gpu_status_shows_install_button_when_not_installed(self):
            self.app.events.put(('gpu-status', {'gpu_name': 'NVIDIA GeForce RTX 3070', 'installed': False}))
            self.app.poll()
            self.assertIsNotNone(self.app.gpu_install_button)
            self.assertFalse(self.app.gpu_installed)

    def test_gpu_status_shows_checkbox_when_already_installed(self):
            self.app.events.put(('gpu-status', {'gpu_name': 'NVIDIA GeForce RTX 3070', 'installed': True}))
            self.app.poll()
            self.assertTrue(self.app.gpu_installed)
            self.assertTrue(self.app.use_gpu.get())

    def test_start_gpu_install_requires_confirmation(self):
            self.app.events.put(('gpu-status', {'gpu_name': 'NVIDIA GeForce RTX 3070', 'installed': False}))
            self.app.poll()
            with patch('scan2read.gui.messagebox.askyesno', return_value=False), \
                 patch('scan2read.gui.subprocess.Popen') as popen:
                self.app._start_gpu_install()
            popen.assert_not_called()
            self.assertIsNone(self.app.gpu_process)

    def test_start_gpu_install_runs_subprocess_when_confirmed(self):
            self.app.events.put(('gpu-status', {'gpu_name': 'NVIDIA GeForce RTX 3070', 'installed': False}))
            self.app.poll()
            process = Mock(stdout=iter([]))
            process.wait.return_value = 0
            with patch('scan2read.gui.messagebox.askyesno', return_value=True), \
                 patch('scan2read.gui.subprocess.Popen', return_value=process) as popen, \
                 patch('scan2read.gui.threading.Thread'):
                self.app._start_gpu_install()
            self.assertIn('gpu-install', popen.call_args.args[0])
            self.assertEqual(str(self.app.gpu_install_button['state']), 'disabled')
            self.assertEqual(str(self.app.start_button['state']), 'disabled')

    def test_gpu_install_success_swaps_button_for_checkbox(self):
            self.app.events.put(('gpu-status', {'gpu_name': 'NVIDIA GeForce RTX 3070', 'installed': False}))
            self.app.poll()
            self.app.gpu_process = Mock()
            self.app.events.put(('gpu-done', 0))
            self.app.poll()
            self.assertIsNone(self.app.gpu_process)
            self.assertTrue(self.app.gpu_installed)
            self.assertTrue(self.app.use_gpu.get())
            self.assertEqual(str(self.app.start_button['state']), 'normal')

    def test_gpu_install_failure_reenables_button(self):
            self.app.events.put(('gpu-status', {'gpu_name': 'NVIDIA GeForce RTX 3070', 'installed': False}))
            self.app.poll()
            self.app.gpu_process = Mock()
            self.app.events.put(('gpu-done', 1))
            self.app.poll()
            self.assertFalse(self.app.gpu_installed)
            self.assertEqual(str(self.app.gpu_install_button['state']), 'normal')

    def test_gpu_install_blocked_while_conversion_running(self):
            self.app.events.put(('gpu-status', {'gpu_name': 'NVIDIA GeForce RTX 3070', 'installed': False}))
            self.app.poll()
            self.app.active = {("a.pdf", "finalize"): {"process": Mock(), "job": {"kind": "finalize", "file": "a.pdf"}}}
            with patch('scan2read.gui.subprocess.Popen') as popen:
                self.app._start_gpu_install()
            popen.assert_not_called()

class DropParsingTests(unittest.TestCase):
    def test_bare_windows_path_backslashes_are_preserved(self):
        self.assertEqual(parse_dropped_paths(r'C:\Users\me\book.pdf'), [r'C:\Users\me\book.pdf'])

    def test_braced_path_with_spaces_and_a_second_bare_path(self):
        data = r'{C:\Users\me\my book.pdf} C:\Users\me\other.pdf'
        self.assertEqual(parse_dropped_paths(data), [r'C:\Users\me\my book.pdf', r'C:\Users\me\other.pdf'])


class AppRootTests(unittest.TestCase):
    def test_frozen_build_launcher_finds_repository_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);launcher=root/'build'/'Scan2Read'/'Scan2Read.exe'
            launcher.parent.mkdir(parents=True);launcher.touch()
            python=root/'.tools'/'paddle-env'/'Scripts'/'python.exe'
            python.parent.mkdir(parents=True);python.touch()
            with patch('scan2read.gui.sys.frozen',True,create=True), \
                 patch('scan2read.gui.sys.executable',str(launcher)):
                self.assertEqual(app_root(),root)


class DpiScaleTests(unittest.TestCase):
    def test_non_windows_always_returns_one(self):
        with patch('scan2read.gui.os.name','posix'):
            self.assertEqual(dpi_scale(),1.0)

    def test_reads_the_scale_factor_from_shcore(self):
        with patch('scan2read.gui.os.name','nt'), \
             patch('ctypes.windll.shcore.SetProcessDpiAwareness'), \
             patch('ctypes.windll.shcore.GetScaleFactorForDevice',return_value=150):
            self.assertEqual(dpi_scale(),1.5)

    def test_falls_back_to_one_when_the_api_is_unavailable(self):
        with patch('scan2read.gui.os.name','nt'), \
             patch('ctypes.windll.shcore.SetProcessDpiAwareness',side_effect=AttributeError), \
             patch('ctypes.windll.user32.SetProcessDPIAware',side_effect=OSError), \
             patch('ctypes.windll.shcore.GetScaleFactorForDevice',return_value=100):
            self.assertEqual(dpi_scale(),1.0)

    def test_falls_back_to_one_if_reading_the_factor_itself_fails(self):
        with patch('scan2read.gui.os.name','nt'), \
             patch('ctypes.windll.shcore.SetProcessDpiAwareness'), \
             patch('ctypes.windll.shcore.GetScaleFactorForDevice',side_effect=OSError):
            self.assertEqual(dpi_scale(),1.0)
