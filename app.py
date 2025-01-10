import whisper
import os
from deep_translator import GoogleTranslator
from edge_tts import Communicate
import asyncio
import logging
import tempfile
import torch
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, concatenate_audioclips, CompositeAudioClip
from multiprocessing import Pool

class LoggerCallback:
    def __init__(self, callback=None):
        self.callback = callback if callback else lambda x: None

    def info(self, message):
        self.callback(message)
        
    def error(self, message):
        self.callback(f"错误: {message}")

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 检查GPU可用性并设置
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
if DEVICE == "cuda":
    # 设置 CUDA 相关参数
    torch.backends.cudnn.enabled = True
    torch.backends.cudnn.benchmark = True
    logger.info(f"使用GPU: {torch.cuda.get_device_name(0)}")
    logger.info(f"CUDA版本: {torch.version.cuda}")
else:
    logger.info("使用CPU处理")

# 设置缓存目录
CACHE_DIR = "model_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# 创建必要的文件夹
os.makedirs("uploads", exist_ok=True)
os.makedirs("subtitles", exist_ok=True)
os.makedirs("audio", exist_ok=True)
os.makedirs("output", exist_ok=True)

# Edge TTS 支持的中文语音列表
CHINESE_VOICES = {
    # 中国大陆
    "zh-CN-XiaoyiNeural": "晓伊 - 女声 (大陆标准普通话)",
    "zh-CN-YunxiNeural": "云希 - 男声 (大陆标准普通话)",
    "zh-CN-YunjianNeural": "云健 - 男声 (大陆标准普通话)",
    "zh-CN-YunyangNeural": "云扬 - 男声 (大陆新闻播报)",
    "zh-CN-XiaochenNeural": "晓辰 - 女声 (大陆标准普通话)",
    "zh-CN-XiaohanNeural": "晓涵 - 女声 (大陆标准普通话)",
    "zh-CN-XiaomengNeural": "晓梦 - 女声 (大陆标准普通话)",
    "zh-CN-XiaomoNeural": "晓墨 - 女声 (大陆标准普通话)",
    "zh-CN-XiaoxuanNeural": "晓萱 - 女声 (大陆标准普通话)",
    "zh-CN-XiaoyanNeural": "晓颜 - 女声 (大陆标准普通话)",
    "zh-CN-XiaoyouNeural": "晓悠 - 女声 (大陆标准普通话)",
    
    # 中国香港
    "zh-HK-HiuGaaiNeural": "晓薇 - 女声 (香港粤语)",
    "zh-HK-HiuMaanNeural": "晓曼 - 女声 (香港粤语)",
    "zh-HK-WanLungNeural": "云龙 - 男声 (香港粤语)",
    
    # 中国台湾
    "zh-TW-HsiaoChenNeural": "晓臻 - 女声 (台湾国语)",
    "zh-TW-YunJheNeural": "云哲 - 男声 (台湾国语)",
    "zh-TW-HsiaoYuNeural": "晓雨 - 女声 (台湾国语)",
}

# 延迟加载模型
model = None
def get_model(callback=None):
    global model
    logger = LoggerCallback(callback)
    if model is None:
        # 添加模型缓存
        cache_file = os.path.join(CACHE_DIR, "whisper_model.pt")
        if os.path.exists(cache_file):
            model = torch.load(cache_file)
        else:
            model = whisper.load_model("medium", download_root=CACHE_DIR)
            torch.save(model, cache_file)
        logger.info("正在加载Whisper模型...")
        try:
            # 尝试加载到GPU
            if DEVICE == "cuda":
                model = model.to(DEVICE)
                logger.info(f"模型已加载到GPU，当前显存使用: {torch.cuda.memory_allocated()/1024**2:.1f}MB")
        except Exception as e:
            logger.error(f"GPU加载失败，回退到CPU: {str(e)}")
            model = whisper.load_model("base", download_root=CACHE_DIR)
        logger.info("Whisper模型加载完成")
    return model

translator = GoogleTranslator(source='en', target='zh-CN')

def get_base_filename(video_path):
    """获取不带扩展名的基础文件名"""
    return os.path.splitext(os.path.basename(video_path))[0]

def process_audio(audio_clip, effects=None):
    if effects:
        if 'volume' in effects:
            audio_clip = audio_clip.volumex(effects['volume'])
        if 'fade' in effects:
            audio_clip = audio_clip.audio_fadein(effects['fade']['in'])
            audio_clip = audio_clip.audio_fadeout(effects['fade']['out'])
    return audio_clip

def generate_subtitles(video_path, callback=None, subtitle_style=None):
    logger = LoggerCallback(callback)
    model = get_model(callback)
    
    try:
        # 设置转录选项
        options = {
            "language": "en",
            "beam_size": 5,
            "best_of": 5,
            "fp16": DEVICE == "cuda"  # 在GPU上启用FP16
        }
        
        # 如果是GPU，先清理显存
        if DEVICE == "cuda":
            torch.cuda.empty_cache()
            logger.info(f"开始转录前显存使用: {torch.cuda.memory_allocated()/1024**2:.1f}MB")
        
        # 确保音频数据在正确的设备上
        result = model.transcribe(video_path, **options)
        
        # 再次清理显存
        if DEVICE == "cuda":
            torch.cuda.empty_cache()
            logger.info(f"转录完成后显存使用: {torch.cuda.memory_allocated()/1024**2:.1f}MB")
        
        # 使用源文件名生成字幕文件名
        base_name = get_base_filename(video_path)
        srt_path = os.path.join("subtitles", f"{base_name}_en.srt")
        os.makedirs("subtitles", exist_ok=True)
        
        def format_timestamp(seconds):
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds - int(seconds)) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
        
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(result["segments"], 1):
                start = format_timestamp(seg["start"])
                end = format_timestamp(seg["end"])
                text = seg["text"].strip()
                f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
        return srt_path

    except Exception as e:
        logger.error(f"字幕生成失败: {str(e)}")
        if DEVICE == "cuda":
            # 如果GPU失败，尝试使用CPU
            logger.info("尝试使用CPU重新生成...")
            # 将模型移回CPU
            model = model.to("cpu")
            result = model.transcribe(video_path, **options)
            base_name = get_base_filename(video_path)
            srt_path = os.path.join("subtitles", f"{base_name}_en.srt")
            os.makedirs("subtitles", exist_ok=True)
            with open(srt_path, "w", encoding="utf-8") as f:
                for i, seg in enumerate(result["segments"], 1):
                    start = format_timestamp(seg["start"])
                    end = format_timestamp(seg["end"])
                    text = seg["text"].strip()
                    f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
            return srt_path
        else:
            raise

def translate_subtitles(en_srt, callback=None):
    logger = LoggerCallback(callback)
    # 从英文字幕文件名获取基础文件名
    base_name = get_base_filename(en_srt.replace("_en.srt", ""))
    cn_srt = os.path.join("subtitles", f"{base_name}_cn.srt")
    
    with open(en_srt, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    with open(cn_srt, "w", encoding="utf-8") as f:
        i = 0
        while i < len(lines):
            if lines[i].strip().isdigit():
                f.write(lines[i])  # 序号
                f.write(lines[i+1])  # 时间轴
                text = lines[i+2].strip()
                translated = translator.translate(text)
                f.write(f"{translated}\n\n")
                i += 4
            else:
                i += 1
    return cn_srt

async def generate_speech(cn_srt, voice_id, callback=None, speed_rate=1.5):
    logger = LoggerCallback(callback)
    audio_files = []
    # 从中文字幕文件名获取基础文件名
    base_name = get_base_filename(cn_srt.replace("_cn.srt", ""))
    os.makedirs("audio", exist_ok=True)
    
    with open(cn_srt, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    i = 0
    total_lines = len(lines)
    max_retries = 3  # 最大重试次数
    retry_delay = 2  # 重试延迟（秒）
    
    while i < total_lines:
        if lines[i].strip().isdigit():
            text = lines[i+2].strip()
            if text:
                for retry in range(max_retries):
                    try:
                        # 修改语速设置逻辑
                        rate_str = ""
                        if speed_rate != 1.0:  # 只有当速率不是1.0时才设置rate参数
                            percentage = int((speed_rate - 1.0) * 100)
                            rate_str = f"+{percentage}%" if percentage > 0 else f"{percentage}%"
                        
                        # 根据是否有速率参数来创建communicate对象
                        if rate_str:
                            communicate = Communicate(text, voice_id, rate=rate_str)
                        else:
                            communicate = Communicate(text, voice_id)
                            
                        audio_file = os.path.join("audio", f"{base_name}_speech_{len(audio_files)}.mp3")
                        await communicate.save(audio_file)
                        audio_files.append((audio_file, lines[i+1].strip()))
                        logger.info(f"已生成 {len(audio_files)} 个语音片段...")
                        break  # 成功生成，跳出重试循环
                    except Exception as e:
                        if retry < max_retries - 1:  # 如果还有重试机会
                            logger.info(f"语音生成失败，{retry + 1}/{max_retries} 次重试...")
                            await asyncio.sleep(retry_delay)  # 等待一段时间后重试
                        else:  # 最后一次重试也失败
                            logger.error(f"语音生成失败: {str(e)}")
                            logger.error(f"语速设置: {speed_rate}")
                            logger.error(f"Rate字符串: {rate_str if 'rate_str' in locals() else 'None'}")
                            logger.error(f"Voice ID: {voice_id}")
                            logger.error(f"文本内容: {text}")
                            raise  # 重新抛出异常
            i += 4
        else:
            i += 1
    return audio_files

def merge_video_audio(video_path, audio_files, cn_srt, callback=None, original_volume=0.1):
    logger = LoggerCallback(callback)
    def parse_timestamp(timestamp):
        h, m, s = timestamp.split(':')
        s, ms = s.split(',')
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    
    video = VideoFileClip(video_path)
    original_audio = video.audio
    
    audio_segments = []
    for audio_file, timing in audio_files:
        start, end = timing.split(' --> ')
        start_time = parse_timestamp(start)
        end_time = parse_timestamp(end)
        audio_clip = AudioFileClip(audio_file)
        audio_segments.append(audio_clip.set_start(start_time))

    if audio_segments:
        new_audio = CompositeAudioClip([original_audio.volumex(original_volume)] + audio_segments)
        final_video = video.set_audio(new_audio)
    else:
        final_video = video

    # 使用源文件名生成输出文件名
    base_name = get_base_filename(video_path)
    output_path = os.path.join("output", f"{base_name}_dubbed.mp4")
    os.makedirs("output", exist_ok=True)
    
    logger.info("正在生成最终视频文件...")
    
    # 基本编码参数
    write_options = {
        'codec': 'libx264',
        'audio_codec': 'aac',
        'audio_bitrate': '192k',
        'threads': 8,
        'fps': video.fps,
        'preset': 'medium',
        'ffmpeg_params': [
            '-movflags', '+faststart',
            '-crf', '18'  # 较高质量的CRF值
        ]
    }
    
    if DEVICE == "cuda":
        try:
            # NVIDIA GPU 加速参数
            write_options.update({
                'codec': 'h264_nvenc',
                'preset': 'hq',        # 使用高质量预设
                'ffmpeg_params': [
                    '-movflags', '+faststart',
                    '-rc:v', 'vbr',    # 可变比特率
                    '-profile:v', 'high',
                    '-spatial-aq', '1',               # 空间自适应量化
                    '-temporal-aq', '1',              # 时间自适应量化
                    '-rc-lookahead', '32'            # 前向预测帧数
                ]
            })
            logger.info("使用NVIDIA GPU加速进行视频编码...")
        except Exception as e:
            logger.error(f"GPU编码器初始化失败，回退到CPU: {str(e)}")
    
    try:
        final_video.write_videofile(
            output_path,
            **write_options
        )
    except Exception as e:
        logger.error(f"视频编码失败: {str(e)}")
        # 如果失败，尝试使用最基本设置
        logger.info("尝试使用基本设置重新编码...")
        basic_options = {
            'codec': 'libx264',
            'audio_codec': 'aac',
            'threads': 8,
            'fps': video.fps
        }
        final_video.write_videofile(output_path, **basic_options)
    
    # 清理资源
    final_video.close()
    if original_audio:
        original_audio.close()
    for audio_clip, _ in zip(audio_segments, audio_files):
        audio_clip.close()
    
    # 清理生成的语音片段
    logger.info("正在清理临时语音文件...")
    for audio_file, _ in audio_files:
        try:
            if os.path.exists(audio_file):
                os.remove(audio_file)
        except Exception as e:
            logger.error(f"清理语音文件失败: {str(e)}")
    
    # 清理audio目录（如果为空）
    try:
        if os.path.exists("audio") and not os.listdir("audio"):
            os.rmdir("audio")
            logger.info("清理空的audio目录")
    except Exception as e:
        logger.error(f"清理audio目录失败: {str(e)}")
        
    return output_path

async def process_video(video_path=None, voice_name="zh-CN-XiaoyiNeural", callback=None):
    logger = LoggerCallback(callback)
    try:
        if not video_path or not os.path.exists(video_path):
            raise ValueError("无效的视频路径")

        logger.info("正在生成英文字幕...")
        en_srt = generate_subtitles(video_path, callback)
        
        logger.info("正在翻译字幕...")
        cn_srt = translate_subtitles(en_srt, callback)
        
        logger.info("正在生成语音...")
        audio_files = await generate_speech(cn_srt, voice_name, callback)
        
        logger.info("正在合并视频和音频...")
        output_path = merge_video_audio(video_path, audio_files, cn_srt, callback)
        
        logger.info(f"处理完成！输出文件：{output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"处理失败: {str(e)}")
        raise 