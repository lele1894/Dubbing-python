import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QPushButton, QLabel, QComboBox, 
                           QFileDialog, QLineEdit, QProgressBar, QTextEdit,
                           QMessageBox, QGroupBox, QSlider, QTabWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent, QAudio
from PyQt5.QtGui import QIcon
import asyncio
import app as dubbing_app
from edge_tts import Communicate
import tempfile
import uuid
import traceback
import logging

class SubtitleEditThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(tuple)  # (en_srt, cn_srt)
    error = pyqtSignal(str)

    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path

    def run(self):
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            self.progress.emit("正在生成英文字幕...")
            en_srt = dubbing_app.generate_subtitles(self.video_path, self.progress.emit)
            
            self.progress.emit("正在翻译字幕...")
            cn_srt = dubbing_app.translate_subtitles(en_srt, self.progress.emit)
            
            self.finished.emit((en_srt, cn_srt))
            
        except Exception as e:
            self.error.emit(str(e))
        finally:
            loop.close()

class PreviewThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, voice_id, speed_rate=1.5, preview_duration=10):
        super().__init__()
        self.voice_id = voice_id
        self.speed_rate = speed_rate
        self.preview_duration = preview_duration
        self.preview_text = self.get_preview_text(preview_duration)
        self.temp_file = None
        self.max_retries = 3  # 最大重试次数

    def get_preview_text(self, duration):
        # 根据时长生成预览文本
        return "这是一段试听音频，用于预览配音效果。" * (duration // 3)

    async def generate_preview(self, loop):
        # 生成唯一的临时文件名
        temp_dir = tempfile.gettempdir()
        self.temp_file = os.path.join(temp_dir, f"preview_{uuid.uuid4().hex}.mp3")
        
        # 尝试生成语音
        rate_str = f"+{int((self.speed_rate - 1) * 100)}%" if self.speed_rate > 1 else f"{int((self.speed_rate - 1) * 100)}%"
        communicate = Communicate(self.preview_text, self.voice_id, rate=rate_str)
        
        # 设置超时时间
        try:
            await asyncio.wait_for(communicate.save(self.temp_file), timeout=10.0)
            return True
        except asyncio.TimeoutError:
            return False
        except Exception as e:
            raise e

    def run(self):
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # 重试机制
            for attempt in range(self.max_retries):
                try:
                    if loop.run_until_complete(self.generate_preview(loop)):
                        if os.path.exists(self.temp_file) and os.path.getsize(self.temp_file) > 0:
                            self.finished.emit(self.temp_file)
                            return
                        else:
                            if attempt == self.max_retries - 1:
                                raise Exception("生成的音频文件无效")
                    else:
                        if attempt == self.max_retries - 1:
                            raise Exception("生成音频超时")
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        raise e
                    continue
                    
            raise Exception("生成音频失败，请重试")
            
        except Exception as e:
            self.error.emit(f"生成试听音频失败: {str(e)}\n请尝试选择其他配音声音或重试")
        finally:
            loop.close()

    def __del__(self):
        # 确保临时文件被清理
        if self.temp_file and os.path.exists(self.temp_file):
            try:
                os.remove(self.temp_file)
            except:
                pass

class DubbingThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, video_path=None, voice_name=None, cn_srt=None, original_volume=0.1, speed_rate=1.5):
        super().__init__()
        self.video_path = video_path
        self.voice_name = voice_name
        self.cn_srt = cn_srt
        self.original_volume = original_volume
        self.speed_rate = speed_rate

    def run(self):
        try:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # 生成语音
            self.progress.emit("正在生成语音...")
            audio_files = loop.run_until_complete(
                dubbing_app.generate_speech(self.cn_srt, self.voice_name, self.progress.emit, self.speed_rate)
            )
            
            # 合并视频和音频
            self.progress.emit("正在合并视频和音频...")
            output_path = dubbing_app.merge_video_audio(
                self.video_path, audio_files, self.cn_srt, self.progress.emit,
                original_volume=self.original_volume
            )
            
            self.finished.emit(output_path)
            
        except Exception as e:
            self.error.emit(str(e))
        finally:
            loop.close()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 设置应用图标
        self.setWindowIcon(QIcon('app.ico'))
        self.initUI()
        self.setupMediaPlayer()
        self.current_en_srt = None
        self.current_cn_srt = None
        self.current_preview_file = None  # 添加当前预览文件路径
        
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        
    def setupMediaPlayer(self):
        # 直接使用旧版本的方式，避免版本兼容性问题
        self.media_player = QMediaPlayer()
        self.media_player.setVolume(50)  # 设置默认音量
        self.media_player.stateChanged.connect(self.mediaStateChanged)
        self.media_player.mediaStatusChanged.connect(self.mediaStatusChanged)
        
    def mediaStateChanged(self, state):
        if state == QMediaPlayer.StoppedState:
            # 如果是正常停止（不是到达结尾），则更新按钮状态
            if self.media_player.mediaStatus() != QMediaPlayer.EndOfMedia:
                self.preview_button.setText('试听')
                self.preview_button.setEnabled(True)
            
    def mediaStatusChanged(self, status):
        if status == QMediaPlayer.EndOfMedia:
            # 到达结尾时重新开始播放
            self.media_player.setPosition(0)
            self.media_player.play()
            
    def initUI(self):
        self.setWindowTitle('视频配音助手')
        self.setMinimumWidth(1000)
        self.setMinimumHeight(800)
        
        # 创建主窗口部件和布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # 本地视频选择
        video_group = QGroupBox("视频输入")
        video_layout = QVBoxLayout()
        
        local_layout = QHBoxLayout()
        self.video_path_edit = QLineEdit()
        self.video_path_edit.setPlaceholderText('选择本地视频文件...')
        video_button = QPushButton('浏览...')
        video_button.clicked.connect(self.select_video)
        local_layout.addWidget(self.video_path_edit)
        local_layout.addWidget(video_button)
        video_layout.addLayout(local_layout)
        
        # 添加生成字幕按钮
        button_layout = QHBoxLayout()
        generate_srt_button = QPushButton('生成字幕')
        generate_srt_button.clicked.connect(self.generate_subtitles)
        button_layout.addWidget(generate_srt_button)
        
        # 添加上传字幕按钮
        upload_srt_button = QPushButton('上传字幕')
        upload_srt_button.clicked.connect(self.upload_subtitles)
        button_layout.addWidget(upload_srt_button)
        
        video_layout.addLayout(button_layout)
        
        video_group.setLayout(video_layout)
        layout.addWidget(video_group)
        
        # 字幕编辑区域
        subtitle_group = QGroupBox("字幕编辑")
        subtitle_layout = QVBoxLayout()
        
        # 使用选项卡组织字幕编辑器
        subtitle_tabs = QTabWidget()
        
        # 英文字幕编辑器
        self.en_subtitle_edit = QTextEdit()
        self.en_subtitle_edit.setReadOnly(True)  # 英文字幕只读
        subtitle_tabs.addTab(self.en_subtitle_edit, "英文字幕")
        
        # 中文字幕编辑器
        self.cn_subtitle_edit = QTextEdit()
        subtitle_tabs.addTab(self.cn_subtitle_edit, "中文字幕")
        
        subtitle_layout.addWidget(subtitle_tabs)
        
        # 添加保存和清空按钮的布局
        subtitle_buttons_layout = QHBoxLayout()
        
        # 添加保存按钮
        save_button = QPushButton('保存字幕')
        save_button.clicked.connect(self.save_subtitles)
        subtitle_buttons_layout.addWidget(save_button)
        
        # 添加清空按钮
        clear_button = QPushButton('清空字幕')
        clear_button.clicked.connect(self.clear_subtitles)
        subtitle_buttons_layout.addWidget(clear_button)
        
        subtitle_layout.addLayout(subtitle_buttons_layout)
        
        subtitle_group.setLayout(subtitle_layout)
        layout.addWidget(subtitle_group)
        
        # 配音选择
        voice_group = QGroupBox("配音选择")
        voice_layout = QVBoxLayout()
        
        # 分区域选择
        region_layout = QHBoxLayout()
        region_label = QLabel('区域:')
        self.region_combo = QComboBox()
        self.region_combo.addItems(['中国大陆', '中国香港', '中国台湾'])
        self.region_combo.currentTextChanged.connect(self.update_voice_list)
        region_layout.addWidget(region_label)
        region_layout.addWidget(self.region_combo)
        voice_layout.addLayout(region_layout)
        
        # 声音选择
        voice_select_layout = QHBoxLayout()
        voice_label = QLabel('声音:')
        self.voice_combo = QComboBox()
        self.preview_button = QPushButton('试听')
        self.preview_button.clicked.connect(self.preview_voice)
        voice_select_layout.addWidget(voice_label)
        voice_select_layout.addWidget(self.voice_combo)
        voice_select_layout.addWidget(self.preview_button)
        voice_layout.addLayout(voice_select_layout)
        
        # 配音音量控制
        volume_layout = QHBoxLayout()
        volume_label = QLabel('配音音量:')
        self.volume_value_label = QLabel('100%')
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(100)
        self.volume_slider.valueChanged.connect(self.setVolume)
        volume_layout.addWidget(volume_label)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_value_label)
        voice_layout.addLayout(volume_layout)
        
        # 添加语音速度控制
        speed_layout = QHBoxLayout()
        speed_label = QLabel('语音速度:')
        self.speed_value_label = QLabel('1.5x')
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setMinimum(50)  # 0.5倍速
        self.speed_slider.setMaximum(300)  # 3.0倍速
        self.speed_slider.setValue(150)  # 默认1.5倍速
        self.speed_slider.valueChanged.connect(self.setSpeed)
        speed_layout.addWidget(speed_label)
        speed_layout.addWidget(self.speed_slider)
        speed_layout.addWidget(self.speed_value_label)
        voice_layout.addLayout(speed_layout)
        
        # 原音频音量控制
        original_volume_layout = QHBoxLayout()
        original_volume_label = QLabel('原音频音量:')
        self.original_volume_value_label = QLabel('10%')  # 添加音量数值显示
        self.original_volume_slider = QSlider(Qt.Horizontal)
        self.original_volume_slider.setMinimum(0)
        self.original_volume_slider.setMaximum(100)
        self.original_volume_slider.setValue(10)  # 默认10%音量
        self.original_volume_slider.valueChanged.connect(self.setOriginalVolume)  # 添加新的连接
        original_volume_layout.addWidget(original_volume_label)
        original_volume_layout.addWidget(self.original_volume_slider)
        original_volume_layout.addWidget(self.original_volume_value_label)
        voice_layout.addLayout(original_volume_layout)
        
        voice_group.setLayout(voice_layout)
        layout.addWidget(voice_group)
        
        # 初始化语音列表
        self.update_voice_list('中国大陆')
        
        # 日志显示
        log_group = QGroupBox("处理日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)
        
        # 开始按钮
        self.start_button = QPushButton('开始处理')
        self.start_button.clicked.connect(self.start_processing)
        layout.addWidget(self.start_button)
        
        self.show()
    
    def generate_subtitles(self):
        video_path = self.video_path_edit.text()
        if not video_path:
            QMessageBox.warning(self, '错误', '请先选择视频文件')
            return
            
        # 清空字幕编辑器
        self.en_subtitle_edit.clear()
        self.cn_subtitle_edit.clear()
        
        # 创建字幕生成线程
        self.subtitle_thread = SubtitleEditThread(video_path)
        self.subtitle_thread.progress.connect(self.log)
        self.subtitle_thread.finished.connect(self.on_subtitles_generated)
        self.subtitle_thread.error.connect(self.on_subtitle_error)
        
        # 禁用按钮
        self.start_button.setEnabled(False)
        self.progress_bar.setMaximum(0)
        
        # 开始处理
        self.subtitle_thread.start()
    
    def on_subtitles_generated(self, srt_files):
        en_srt, cn_srt = srt_files
        self.current_en_srt = en_srt
        self.current_cn_srt = cn_srt
        
        # 显示字幕内容
        with open(en_srt, 'r', encoding='utf-8') as f:
            self.en_subtitle_edit.setText(f.read())
        with open(cn_srt, 'r', encoding='utf-8') as f:
            self.cn_subtitle_edit.setText(f.read())
            
        # 恢复按钮状态
        self.start_button.setEnabled(True)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        
        self.log("字幕生成完成，您可以编辑中文字幕后开始处理")
    
    def on_subtitle_error(self, error_message):
        self.start_button.setEnabled(True)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        QMessageBox.critical(self, '错误', f'生成字幕失败：{error_message}')
    
    def save_subtitles(self):
        if not self.current_cn_srt:
            QMessageBox.warning(self, '错误', '没有可保存的字幕')
            return
            
        try:
            # 保存中文字幕
            with open(self.current_cn_srt, 'w', encoding='utf-8') as f:
                f.write(self.cn_subtitle_edit.toPlainText())
            self.log("字幕保存成功")
        except Exception as e:
            QMessageBox.critical(self, '错误', f'保存字幕失败：{str(e)}')
    
    def setVolume(self, value):
        self.media_player.setVolume(value)
        self.volume_value_label.setText(f"{value}%")  # 更新音量显示
        
    def setOriginalVolume(self, value):
        self.original_volume_value_label.setText(f"{value}%")  # 更新原音频音量显示
    
    def setSpeed(self, value):
        self.speed_value_label.setText(f"{value / 100.0}x")
    
    def update_voice_list(self, region):
        self.voice_combo.clear()
        for voice_id, voice_name in dubbing_app.CHINESE_VOICES.items():
            if region == '中国大陆' and voice_id.startswith('zh-CN-'):
                self.voice_combo.addItem(voice_name, voice_id)
            elif region == '中国香港' and voice_id.startswith('zh-HK-'):
                self.voice_combo.addItem(voice_name, voice_id)
            elif region == '中国台湾' and voice_id.startswith('zh-TW-'):
                self.voice_combo.addItem(voice_name, voice_id)
        
    def select_video(self):
        def is_valid_video(file_path):
            valid_extensions = {'.mp4', '.avi', '.mkv', '.mov'}
            return os.path.splitext(file_path)[1].lower() in valid_extensions
        
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频文件",
            "",
            "视频文件 (*.mp4 *.avi *.mkv *.mov);;所有文件 (*.*)"
        )
        
        if file_name and is_valid_video(file_name):
            self.video_path_edit.setText(file_name)
        else:
            QMessageBox.warning(self, '错误', '请选择有效的视频文件')
        
    def log(self, message):
        self.log_text.append(message)
        
    def cleanup_preview(self):
        """清理预览相关资源"""
        try:
            if self.media_player.state() == QMediaPlayer.PlayingState:
                self.media_player.stop()
            self.media_player.setMedia(None)
            
            if hasattr(self, 'current_preview_file') and self.current_preview_file:
                if os.path.exists(self.current_preview_file):
                    try:
                        os.remove(self.current_preview_file)
                    except:
                        pass
                self.current_preview_file = None
        except:
            pass

    def preview_voice(self):
        # 如果正在播放，则停止
        if self.media_player.state() == QMediaPlayer.PlayingState:
            self.cleanup_preview()
            self.preview_button.setText('试听')
            return
            
        voice_id = self.voice_combo.currentData()
        if not voice_id:
            return
            
        # 禁用试听按钮
        self.preview_button.setEnabled(False)
        self.preview_button.setText('生成试听...')
        
        # 清理旧的预览
        self.cleanup_preview()
        
        # 创建预览线程
        self.preview_thread = PreviewThread(voice_id, self.speed_slider.value() / 100.0)
        self.preview_thread.finished.connect(self.on_preview_finished)
        self.preview_thread.error.connect(self.on_preview_error)
        self.preview_thread.start()
        
    def on_preview_finished(self, audio_path):
        self.preview_button.setEnabled(True)
        self.current_preview_file = audio_path  # 保存当前预览文件路径
        
        # 使用内置播放器播放音频
        try:
            url = QUrl.fromLocalFile(audio_path)
            content = QMediaContent(url)
            self.media_player.setMedia(content)
            self.media_player.play()
            self.preview_button.setText('停止')
        except Exception as e:
            QMessageBox.warning(self, '错误', f'播放音频失败：{str(e)}')
            self.preview_button.setText('试听')
            
    def on_preview_error(self, error_message):
        self.preview_button.setEnabled(True)
        self.preview_button.setText('试听')
        QMessageBox.warning(self, '错误', f'生成试听音频失败：{error_message}')
        
    def start_processing(self):
        # 检查输入
        video_path = self.video_path_edit.text()
        
        if not video_path:
            QMessageBox.warning(self, '错误', '请选择本地视频文件')
            return
            
        # 禁用界面元素
        self.start_button.setEnabled(False)
        self.progress_bar.setMaximum(0)
        self.log_text.clear()
        
        # 如果已有字幕，保存当前字幕
        if self.current_cn_srt:
            self.save_subtitles()
            self.process_with_subtitles()
        else:
            # 创建字幕生成线程
            self.subtitle_thread = SubtitleEditThread(video_path)
            self.subtitle_thread.progress.connect(self.log)
            self.subtitle_thread.finished.connect(self.on_auto_subtitles_generated)
            self.subtitle_thread.error.connect(self.on_subtitle_error)
            self.subtitle_thread.start()
            
    def on_auto_subtitles_generated(self, srt_files):
        en_srt, cn_srt = srt_files
        self.current_en_srt = en_srt
        self.current_cn_srt = cn_srt
        
        # 显示字幕内容
        with open(en_srt, 'r', encoding='utf-8') as f:
            self.en_subtitle_edit.setText(f.read())
        with open(cn_srt, 'r', encoding='utf-8') as f:
            self.cn_subtitle_edit.setText(f.read())
            
        # 直接继续处理
        self.process_with_subtitles()
        
    def process_with_subtitles(self):
        video_path = self.video_path_edit.text()
        
        # 创建处理线程
        self.dubbing_thread = DubbingThread(
            video_path=video_path,
            voice_name=self.voice_combo.currentData(),
            cn_srt=self.current_cn_srt,
            original_volume=self.original_volume_slider.value() / 100.0,  # 转换为0-1的值
            speed_rate=self.speed_slider.value() / 100.0  # 转换为倍速值
        )
        
        # 连接信号
        self.dubbing_thread.progress.connect(self.log)
        self.dubbing_thread.finished.connect(self.on_processing_finished)
        self.dubbing_thread.error.connect(self.on_processing_error)
        
        # 开始处理
        self.dubbing_thread.start()
        
    def on_processing_finished(self, output_path):
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(100)
        self.start_button.setEnabled(True)
        self.log(f"处理完成！输出文件：{output_path}")
        
        reply = QMessageBox.question(
            self,
            '处理完成',
            f'视频处理完成！\n输出文件：{output_path}\n\n是否打开输出文件夹？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            os.startfile(os.path.dirname(output_path))
        
    def on_processing_error(self, error_message):
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.start_button.setEnabled(True)
        
        # 记录详细错误信息
        error_details = traceback.format_exc()
        logging.error(f"处理失败:\n{error_details}")
        
        # 显示更友好的错误信息
        error_dialog = QMessageBox(self)
        error_dialog.setIcon(QMessageBox.Critical)
        error_dialog.setWindowTitle("错误")
        error_dialog.setText("处理失败")
        error_dialog.setDetailedText(error_details)
        error_dialog.exec_()
        
    def closeEvent(self, event):
        # 关闭窗口时清理所有资源
        self.cleanup_preview()
        
        # 等待所有线程完成
        if hasattr(self, 'preview_thread') and self.preview_thread:
            self.preview_thread.wait()
        if hasattr(self, 'subtitle_thread') and self.subtitle_thread:
            self.subtitle_thread.wait()
        if hasattr(self, 'dubbing_thread') and self.dubbing_thread:
            self.dubbing_thread.wait()
            
        event.accept()

    def upload_subtitles(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "选择字幕文件",
            "",
            "字幕文件 (*.srt);;所有文件 (*.*)"
        )
        if file_name:
            try:
                # 读取上传的字幕文件
                with open(file_name, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 将字幕内容显示在中文字幕编辑框中
                self.cn_subtitle_edit.setText(content)
                
                # 获取视频文件名作为基础名
                video_path = self.video_path_edit.text()
                if not video_path:
                    QMessageBox.warning(self, '提示', '请先选择视频文件，以便正确命名字幕文件')
                    return
                
                # 使用视频文件名保存字幕文件
                base_name = dubbing_app.get_base_filename(video_path)
                os.makedirs("subtitles", exist_ok=True)
                self.current_cn_srt = os.path.join("subtitles", f"{base_name}_cn.srt")
                
                with open(self.current_cn_srt, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                self.log("字幕文件加载成功")
            except Exception as e:
                QMessageBox.critical(self, '错误', f'加载字幕文件失败：{str(e)}')

    def clear_subtitles(self):
        """清空字幕内容和相关变量"""
        reply = QMessageBox.question(
            self,
            '确认清空',
            '确定要清空所有字幕内容吗？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 清空编辑器内容
            self.en_subtitle_edit.clear()
            self.cn_subtitle_edit.clear()
            
            # 清空字幕文件路径
            self.current_en_srt = None
            self.current_cn_srt = None
            
            self.log("字幕已清空")

def main():
    # 忽略弃用警告
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    
    # 设置事件循环策略
    if sys.platform.startswith('win'):
        # Windows平台使用 SelectorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    app = QApplication(sys.argv)
    # 设置应用程序图标
    app.setWindowIcon(QIcon('app.ico'))
    window = MainWindow()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main() 