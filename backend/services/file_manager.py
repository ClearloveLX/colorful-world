import os
import shutil
from pathlib import Path
from datetime import datetime


class FileManager:
    """文件管理器：处理图片的移动和分类"""
    
    def __init__(self, source_folder=None):
        self.source_folder = source_folder
        self.base_output_folder = "output"
        self.good_folder = os.path.join(self.base_output_folder, "good")
        self.recycle_bin_folder = os.path.join(self.base_output_folder, "recycle_bin")
        
        # 确保输出文件夹存在
        self.create_folders()
    
    def create_folders(self):
        """创建必要的文件夹"""
        os.makedirs(self.good_folder, exist_ok=True)
        os.makedirs(self.recycle_bin_folder, exist_ok=True)
    
    def set_source_folder(self, folder):
        """设置源文件夹"""
        self.source_folder = folder
    
    def get_image_files(self):
        """获取源文件夹中的所有媒体文件"""
        if not self.source_folder or not os.path.exists(self.source_folder):
            return []
        
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.mpeg', '.mpg', '.m4v', '.ts', '.m2ts', '.wmv', '.3gp', '.mp3', '.m4a'}
        exts = image_extensions | video_extensions
        seen = set()
        files = []
        for ext in exts:
            for f in Path(self.source_folder).glob(f"*{ext}"):
                p = str(f)
                k = os.path.normcase(p)
                if k not in seen:
                    seen.add(k)
                    files.append(p)
        return files

    def get_video_files(self):
        """仅获取视频文件"""
        if not self.source_folder or not os.path.exists(self.source_folder):
            return []
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.mpeg', '.mpg', '.m4v', '.ts', '.m2ts', '.wmv', '.3gp', '.mp3', '.m4a'}
        seen = set()
        files = []
        for ext in video_extensions:
            for f in Path(self.source_folder).glob(f"*{ext}"):
                p = str(f)
                k = os.path.normcase(p)
                if k not in seen:
                    seen.add(k)
                    files.append(p)
        return files
    
    def move_to_person_folder(self, image_path, person_id):
        """将图片移动到对应人物的文件夹"""
        person_folder = os.path.join(self.good_folder, person_id)
        os.makedirs(person_folder, exist_ok=True)
        
        self._move_file(image_path, person_folder)
    
    def move_to_good_folder(self, image_path):
        """将图片移动到好看文件夹（未识别到人脸）"""
        self._move_file(image_path, self.good_folder)
    
    def move_to_recycle_bin(self, image_path):
        """将图片移动到回收站文件夹"""
        self._move_file(image_path, self.recycle_bin_folder)
    
    def _move_file(self, source_path, dest_folder):
        """移动文件到目标文件夹"""
        try:
            if not os.path.exists(source_path):
                print(f"文件不存在: {source_path}")
                return
            
            filename = os.path.basename(source_path)
            dest_path = os.path.join(dest_folder, filename)
            
            # 如果目标文件已存在，添加时间戳
            if os.path.exists(dest_path):
                name, ext = os.path.splitext(filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{name}_{timestamp}{ext}"
                dest_path = os.path.join(dest_folder, filename)
            
            shutil.move(source_path, dest_path)
            print(f"已移动: {source_path} -> {dest_path}")
            
        except Exception as e:
            print(f"移动文件失败 {source_path}: {str(e)}")
            # 如果移动失败，尝试复制
            try:
                filename = os.path.basename(source_path)
                dest_path = os.path.join(dest_folder, filename)
                
                if os.path.exists(dest_path):
                    name, ext = os.path.splitext(filename)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{name}_{timestamp}{ext}"
                    dest_path = os.path.join(dest_folder, filename)
                
                shutil.copy2(source_path, dest_path)
                os.remove(source_path)
                print(f"已复制并删除: {source_path} -> {dest_path}")
            except Exception as e2:
                print(f"复制文件也失败 {source_path}: {str(e2)}")




