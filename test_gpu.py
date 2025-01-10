import sys
import os
import logging

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_imports():
    logger.info("=== 检查必要包的导入 ===")
    
    # 检查PyTorch
    try:
        import torch
        logger.info(f"PyTorch导入成功，版本: {torch.__version__}")
    except ImportError as e:
        logger.error(f"PyTorch导入失败: {str(e)}")
        logger.info("请尝试重新安装PyTorch: pip install torch")
        return None
        
    # 检查Whisper
    try:
        import whisper
        logger.info("Whisper导入成功")
    except ImportError as e:
        logger.error(f"Whisper导入失败: {str(e)}")
        logger.info("请安装Whisper: pip install openai-whisper")
        return None
        
    return torch, whisper

def check_gpu_details(torch):
    logger.info("\n=== 系统环境检查 ===")
    logger.info(f"Python版本: {sys.version}")
    logger.info(f"PyTorch版本: {torch.__version__}")
    logger.info(f"是否支持CUDA构建: {torch.backends.cuda.is_built()}")
    
    if not torch.cuda.is_available():
        logger.info("\n=== GPU不可用的可能原因 ===")
        
        # 检查CUDA工具包
        try:
            import torch.cuda
            logger.info("CUDA工具包已安装")
        except ImportError:
            logger.error("CUDA工具包未安装")
            
        # 检查NVIDIA驱动
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            driver_version = pynvml.nvmlSystemGetDriverVersion()
            logger.info(f"NVIDIA驱动版本: {driver_version}")
            logger.info(f"GPU总内存: {info.total / 1024**2:.1f}MB")
        except:
            logger.error("无法获取NVIDIA驱动信息，可能未安装驱动或驱动不正确")
            
        # 检查CUDA环境变量
        cuda_path = os.environ.get('CUDA_PATH')
        if cuda_path:
            logger.info(f"CUDA_PATH环境变量: {cuda_path}")
        else:
            logger.warning("未设置CUDA_PATH环境变量")
            
        # 建议解决方案
        logger.info("\n=== 建议解决方案 ===")
        logger.info("1. 确保已安装NVIDIA显卡驱动")
        logger.info("2. 安装与PyTorch匹配的CUDA版本")
        logger.info("3. 检查CUDA环境变量设置")
        logger.info("4. 可以尝试重新安装支持CUDA的PyTorch版本:")
        logger.info("   pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118")

def test_gpu():
    # 首先检查导入
    imports = check_imports()
    if imports is None:
        return
        
    torch, whisper = imports
    
    # 进行详细检查
    check_gpu_details(torch)
    
    # 1. 测试CUDA是否可用
    logger.info("\n=== CUDA 可用性测试 ===")
    cuda_available = torch.cuda.is_available()
    logger.info(f"CUDA 是否可用: {cuda_available}")
    
    if cuda_available:
        # 显示CUDA版本和设备信息
        logger.info(f"CUDA 版本: {torch.version.cuda}")
        logger.info(f"当前GPU设备: {torch.cuda.get_device_name(0)}")
        logger.info(f"GPU数量: {torch.cuda.device_count()}")
        logger.info(f"当前CUDA设备索引: {torch.cuda.current_device()}")
        logger.info(f"CUDA设备属性: {torch.cuda.get_device_properties(0)}")
        
        # 显示当前GPU内存使用情况
        logger.info(f"当前显存使用: {torch.cuda.memory_allocated()/1024**2:.1f}MB")
        logger.info(f"当前显存缓存: {torch.cuda.memory_reserved()/1024**2:.1f}MB")
        
        # 测试简单的GPU运算
        logger.info("\n=== GPU 运算测试 ===")
        try:
            # 创建一个大矩阵并移动到GPU
            x = torch.randn(1000, 1000).cuda()
            y = torch.randn(1000, 1000).cuda()
            
            # 执行矩阵乘法
            z = torch.matmul(x, y)
            
            logger.info("GPU矩阵运算测试成功")
            logger.info(f"运算后显存使用: {torch.cuda.memory_allocated()/1024**2:.1f}MB")
        except Exception as e:
            logger.error(f"GPU运算测试失败: {str(e)}")
    
    # 2. 测试Whisper模型
    logger.info("\n=== Whisper模型测试 ===")
    try:
        # 设置缓存目录
        cache_dir = "model_cache"
        os.makedirs(cache_dir, exist_ok=True)
        
        # 加载模型
        logger.info("正在加载Whisper模型...")
        model = whisper.load_model("base", download_root=cache_dir)
        
        if cuda_available:
            # 将模型移动到GPU
            logger.info("正在将模型移动到GPU...")
            model = model.to("cuda")
            logger.info(f"模型加载后显存使用: {torch.cuda.memory_allocated()/1024**2:.1f}MB")
        
        # 测试模型是否在正确的设备上
        logger.info(f"模型当前设备: {next(model.parameters()).device}")
        
        # 清理显存
        if cuda_available:
            torch.cuda.empty_cache()
            logger.info(f"清理后显存使用: {torch.cuda.memory_allocated()/1024**2:.1f}MB")
        
        logger.info("Whisper模型测试完成")
        
    except Exception as e:
        logger.error(f"Whisper模型测试失败: {str(e)}")

def test_audio_processing():
    # 测试音频处理功能
    pass

def test_subtitle_generation():
    # 测试字幕生成功能
    pass

def test_video_merging():
    # 测试视频合并功能
    pass

if __name__ == "__main__":
    test_gpu() 