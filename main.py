import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os
import shutil
import zipfile
import tempfile
import base64
import io
import re
import queue
import threading
from PIL import Image, ImageTk, ImageDraw
import cv2
from pathlib import Path
from datetime import datetime
import ctypes
import functools

from backend.data.database import Database
from backend.services.file_manager import FileManager

# 数据根目录可通过环境变量 CW_DATA_ROOT 配置，默认使用项目内的 data 目录
def get_data_root():
    try:
        env = os.environ.get('CW_DATA_ROOT')
        if env:
            return os.path.abspath(env)
    except Exception:
        pass
    return os.path.abspath(os.path.join(os.path.dirname(__file__), 'data'))

def _win_logical_cmp(a, b):
    try:
        return ctypes.windll.Shlwapi.StrCmpLogicalW(str(a), str(b))
    except Exception:
        return (a > b) - (a < b)


class ImageClassifierApp:
    VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.mpeg', '.mpg', '.m4v', '.ts', '.m2ts', '.wmv', '.3gp'}
    AUDIO_EXTENSIONS = {'.mp3', '.m4a'}
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}

    def __init__(self, root):
        self.root = root
        self.root.title("图片分类管理界面")
        self.root.geometry("1400x900")
        
        # 初始化数据库
        self.db = Database()
        self.file_manager = FileManager()
        
        # 当前图片信息
        self.current_image_path = None
        self.current_file_id = None
        self.current_image_index = -1
        self.image_files = []

        # 预加载缓存
        self._preloaded_photo = None
        self._preloaded_index = -1
        self._preloaded_path = None
        
        # 自动下一张模式
        self.auto_next = tk.BooleanVar(value=True)
        
        # 上一次选择的分类（用于保留选择）
        self.last_selected_model_id = None  # 改为单选，存储单个ID
        self.last_selected_tag_ids = []
        self.image_preset_var = tk.StringVar(value="")
        self.image_preset_combo = None
        self.image_preset_cache = {"items": [], "by_name": {}, "by_id": {}}
        self.video_preset_cache = {"items": [], "by_name": {}, "by_id": {}}
        self.video_preset_context = None
        
        # 跟踪打开的对话框，防止同时打开多个
        self.current_dialog = None
        self.video_cap = None
        self.video_playing = False
        self.video_after_id = None
        self.video_total_frames = 0
        self.video_fps = 0.0
        self.video_is_video = False
        self.gif_img = None
        self.gif_playing = False
        self.gif_after_id = None
        self.gif_total_frames = 0
        self.gif_durations_ms = []
        self.gif_current_index = 0
        self.gif_is_gif = False
        
        # 创建界面
        self.create_widgets()
        
        # 绑定键盘快捷键
        self.bind_shortcuts()
        
        # 窗口显示后，确保sash位置正确（延迟执行，确保窗口完全渲染）
        def on_window_ready():
            self.maintain_sash_position()
        self.root.after(500, on_window_ready)
    
    def load_image_from_base64(self, base64_string):
        """从base64字符串加载图片"""
        if not base64_string:
            return None
        try:
            # 尝试解码base64字符串
            image_data = base64.b64decode(base64_string)
            img = Image.open(io.BytesIO(image_data))
            return img
        except Exception:
            # 如果不是base64，可能是文件路径（兼容旧数据）
            if os.path.exists(base64_string):
                try:
                    return Image.open(base64_string)
                except Exception:
                    return None
            return None

    def _get_active_tag_lookup(self):
        tags = self.db.get_tags_with_category_name(only_active=True)
        return {tag['id']: tag for tag in tags}

    def _get_selected_tag_ids(self, tag_vars=None):
        source = tag_vars if tag_vars is not None else self.tag_vars
        return [tag_id for tag_id, var in source.items() if var.get()]

    def _set_tag_selection(self, tag_ids, tag_vars=None):
        source = tag_vars if tag_vars is not None else self.tag_vars
        target_ids = set(tag_ids or [])
        for tag_id, var in source.items():
            var.set(tag_id in target_ids)

    def _load_presets(self, media_type):
        items = self.db.list_presets(media_type)
        cache = {
            "items": items,
            "by_name": {item['name']: item for item in items},
            "by_id": {item['preset_id']: item for item in items},
        }
        if media_type == 'image':
            self.image_preset_cache = cache
        else:
            self.video_preset_cache = cache
        return cache

    def refresh_image_preset_controls(self):
        cache = self._load_presets('image')
        if self.image_preset_combo is not None:
            names = [''] + [item['name'] for item in cache['items']]
            self.image_preset_combo['values'] = names
            if self.image_preset_var.get() not in cache['by_name']:
                self.image_preset_var.set('')

    def _apply_preset_tags_to_vars(self, media_type, preset, tag_vars=None):
        available_tags = self._get_active_tag_lookup()
        preset_tag_ids = preset.get('tags') or []
        missing = [tag_id for tag_id in preset_tag_ids if tag_id not in available_tags]
        if missing:
            raise ValueError(f"预制中存在已失效标签，无法应用：{', '.join(missing)}")
        self._set_tag_selection(preset_tag_ids, tag_vars=tag_vars)
        self.last_selected_tag_ids = list(preset_tag_ids)

    def _get_current_preset(self, media_type, preset_name=None, cache=None):
        name = (preset_name or '').strip()
        if not name:
            return None
        current_cache = cache or (self.image_preset_cache if media_type == 'image' else self.video_preset_cache)
        preset = current_cache.get('by_name', {}).get(name)
        if not preset:
            current_cache = self._load_presets(media_type)
            preset = current_cache.get('by_name', {}).get(name)
        if not preset:
            return None
        return self.db.get_preset(media_type, preset['preset_id'])

    def _restore_current_preset_tags(self, media_type, preset_name=None, tag_vars=None):
        preset = self._get_current_preset(media_type, preset_name=preset_name)
        if not preset:
            return None
        self._apply_preset_tags_to_vars(media_type, preset, tag_vars=tag_vars)
        return preset

    def _overwrite_selected_preset(self, media_type, preset_name, tag_ids, parent=None, tag_vars=None):
        name = (preset_name or '').strip()
        if not name:
            raise ValueError("请先选择一个预制")
        if not tag_ids:
            raise ValueError("请先勾选至少一个标签")
        preset = self._get_current_preset(media_type, preset_name=name)
        if not preset:
            raise ValueError("当前预制不存在或已删除")
        if not messagebox.askyesno(
            "确认覆盖",
            f"确定用当前勾选标签覆盖预制“{preset['name']}”吗？",
            parent=parent,
        ):
            return None
        updated = self.db.update_preset(media_type, preset['preset_id'], tags=tag_ids)
        if not updated:
            raise ValueError("覆盖预制失败")
        self._load_presets(media_type)
        self._apply_preset_tags_to_vars(media_type, updated, tag_vars=tag_vars)
        return updated

    def _cycle_preset_selection(self, preset_var, media_type, step, apply_callback, combo=None):
        cache = self.image_preset_cache if media_type == 'image' else self.video_preset_cache
        items = cache.get('items') or self._load_presets(media_type).get('items', [])
        if not items:
            return False
        names = [''] + [item['name'] for item in items]
        current_name = (preset_var.get() or '').strip()
        if current_name in names:
            current_index = names.index(current_name)
            next_index = max(0, min(len(names) - 1, current_index + step))
        else:
            next_index = 1 if step >= 0 and len(names) > 1 else 0
        if current_name == names[next_index]:
            return False
        preset_var.set(names[next_index])
        if combo is not None:
            try:
                combo.current(next_index)
            except Exception:
                pass
        apply_callback()
        return True

    def on_global_preset_mousewheel(self, event):
        step = -1 if event.delta > 0 else 1
        try:
            event_top = event.widget.winfo_toplevel()
        except Exception:
            event_top = None

        ctx = self.video_preset_context
        if ctx:
            try:
                if ctx['window'].winfo_exists() and event_top == ctx['window']:
                    if self._cycle_preset_selection(
                        ctx['var'],
                        'video',
                        step,
                        ctx['apply'],
                        combo=ctx['combo'],
                    ):
                        return "break"
                    return "break"
            except Exception:
                self.video_preset_context = None

        if event_top == self.root:
            if self._cycle_preset_selection(
                self.image_preset_var,
                'image',
                step,
                self.apply_selected_image_preset,
                combo=self.image_preset_combo,
            ):
                return "break"
            return "break"
        return None

    def on_image_preset_mousewheel(self, event):
        if not (event.state & 0x0004):
            return None
        return self.on_global_preset_mousewheel(event)

    def apply_selected_image_preset(self, event=None):
        name = (self.image_preset_var.get() or '').strip()
        if not name:
            return
        cache = self.image_preset_cache or self._load_presets('image')
        preset = cache['by_name'].get(name)
        if not preset:
            messagebox.showerror("错误", "未找到选中的预制")
            self.refresh_image_preset_controls()
            return
        try:
            full_preset = self.db.get_preset('image', preset['preset_id'])
            if not full_preset:
                raise ValueError("预制不存在或已删除")
            self._apply_preset_tags_to_vars('image', full_preset)
            self.status_label.config(text=f"已应用图片预制：{full_preset['name']}")
        except Exception as e:
            messagebox.showerror("错误", f"应用预制失败：\n{str(e)}")
            self.refresh_image_preset_controls()

    def save_current_image_preset(self):
        selected_tag_ids = self._get_selected_tag_ids()
        if not selected_tag_ids:
            messagebox.showwarning("警告", "请先勾选至少一个标签")
            return
        name = simpledialog.askstring("保存为预制", "请输入预制名称（50字内）:", parent=self.root)
        if name is None:
            return
        try:
            preset_id = self.db.create_preset('image', name=name, sort_order=len(self.image_preset_cache.get('items', [])), tags=selected_tag_ids)
            self.refresh_image_preset_controls()
            preset = self.db.get_preset('image', preset_id)
            if preset:
                self.image_preset_var.set(preset['name'])
            self.status_label.config(text=f"图片预制已保存：{name.strip()}")
        except Exception as e:
            messagebox.showerror("错误", f"保存预制失败：\n{str(e)}")

    def overwrite_current_image_preset(self):
        try:
            updated = self._overwrite_selected_preset(
                'image',
                self.image_preset_var.get(),
                self._get_selected_tag_ids(),
                parent=self.root,
            )
            if updated:
                self.refresh_image_preset_controls()
                self.image_preset_var.set(updated['name'])
                self.status_label.config(text=f"图片预制已覆盖：{updated['name']}")
        except Exception as e:
            messagebox.showerror("错误", f"覆盖预制失败：\n{str(e)}")

    def open_image_preset_manager(self):
        self.open_preset_manager('image', parent=self.root, on_change=self.refresh_image_preset_controls)

    def open_preset_manager(self, media_type, parent=None, on_change=None):
        parent_window = parent or self.root
        title_prefix = "图片" if media_type == 'image' else "视频"
        win = tk.Toplevel(parent_window)
        win.title(f"{title_prefix}预制管理")
        win.geometry("760x520")
        win.transient(parent_window)

        list_frame = ttk.Frame(win)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ('name', 'sort_order', 'tags')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', selectmode='browse')
        tree.heading('name', text='名称')
        tree.heading('sort_order', text='排序')
        tree.heading('tags', text='标签数')
        tree.column('name', width=280)
        tree.column('sort_order', width=80, anchor=tk.CENTER)
        tree.column('tags', width=80, anchor=tk.CENTER)
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        editor = ttk.LabelFrame(win, text="编辑")
        editor.pack(fill=tk.X, padx=10, pady=(0, 10))
        name_var = tk.StringVar()
        order_var = tk.StringVar()
        info_var = tk.StringVar(value="请选择一条预制")

        ttk.Label(editor, text="名称").grid(row=0, column=0, padx=5, pady=5, sticky='w')
        name_entry = ttk.Entry(editor, textvariable=name_var, width=32)
        name_entry.grid(row=0, column=1, padx=5, pady=5, sticky='ew')
        ttk.Label(editor, text="排序").grid(row=0, column=2, padx=5, pady=5, sticky='w')
        order_entry = ttk.Entry(editor, textvariable=order_var, width=8)
        order_entry.grid(row=0, column=3, padx=5, pady=5, sticky='w')
        ttk.Label(editor, textvariable=info_var).grid(row=1, column=0, columnspan=4, padx=5, pady=(0, 5), sticky='w')
        editor.grid_columnconfigure(1, weight=1)

        state = {"items": [], "selected_id": None}

        def refresh_tree(select_id=None):
            presets = self.db.list_presets(media_type)
            state["items"] = presets
            state["selected_id"] = select_id if select_id else state.get("selected_id")
            tree.delete(*tree.get_children())
            for item in presets:
                tree.insert('', tk.END, iid=item['preset_id'], values=(item['name'], item['sort_order'], len(item.get('tags') or [])))
            target_id = state["selected_id"]
            if target_id and tree.exists(target_id):
                tree.selection_set(target_id)
                tree.focus(target_id)
                tree.see(target_id)
                on_tree_select()
            else:
                state["selected_id"] = None
                name_var.set('')
                order_var.set('')
                info_var.set("请选择一条预制")
            if on_change:
                on_change()

        def get_selected_preset():
            preset_id = state.get("selected_id")
            if not preset_id:
                return None
            return self.db.get_preset(media_type, preset_id)

        def on_tree_select(event=None):
            selection = tree.selection()
            if not selection:
                state["selected_id"] = None
                return
            preset_id = selection[0]
            preset = self.db.get_preset(media_type, preset_id)
            if not preset:
                refresh_tree()
                return
            state["selected_id"] = preset_id
            name_var.set(preset['name'])
            order_var.set(str(preset['sort_order']))
            active_tags = self._get_active_tag_lookup()
            tag_names = [active_tags[tag_id]['name'] for tag_id in preset.get('tags') or [] if tag_id in active_tags]
            info_var.set("标签：" + ("、".join(tag_names) if tag_names else "无"))

        def save_changes():
            preset = get_selected_preset()
            if not preset:
                messagebox.showwarning("警告", "请先选择一个预制")
                return
            try:
                new_order = int((order_var.get() or '').strip())
            except Exception:
                messagebox.showerror("错误", "排序必须是整数")
                return
            try:
                updated = self.db.update_preset(
                    media_type,
                    preset['preset_id'],
                    name=name_var.get(),
                    sort_order=new_order,
                    tags=preset.get('tags') or []
                )
                refresh_tree(updated['preset_id'])
            except Exception as e:
                messagebox.showerror("错误", f"保存失败：\n{str(e)}")

        def delete_selected():
            preset = get_selected_preset()
            if not preset:
                messagebox.showwarning("警告", "请先选择一个预制")
                return
            if not messagebox.askyesno("确认删除", f"确定删除预制“{preset['name']}”吗？", parent=win):
                return
            try:
                self.db.delete_preset(media_type, preset['preset_id'])
                refresh_tree()
            except Exception as e:
                messagebox.showerror("错误", f"删除失败：\n{str(e)}")

        action_frame = ttk.Frame(win)
        action_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(action_frame, text="保存修改", command=save_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="删除预制", command=delete_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="刷新", command=lambda: refresh_tree(state.get("selected_id"))).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="关闭", command=win.destroy).pack(side=tk.RIGHT, padx=5)

        tree.bind('<<TreeviewSelect>>', on_tree_select)
        refresh_tree()
    
    def create_widgets(self):
        # 顶部工具栏
        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(toolbar, text="选择源文件夹", command=self.select_source_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="刷新列表", command=self.scan_folder).pack(side=tk.LEFT, padx=5)

        ttk.Button(toolbar, text="模特管理", command=self.open_model_manager).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="标签管理", command=self.open_tag_manager).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="文件回显", command=self.open_file_browser).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="导出", command=self.open_export_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="视频处理", command=self.open_video_processor).pack(side=tk.LEFT, padx=5)
        
        # 自动下一张开关
        auto_check = ttk.Checkbutton(toolbar, text="自动下一张", variable=self.auto_next)
        auto_check.pack(side=tk.LEFT, padx=10)
        
        # 源文件夹路径显示
        self.source_folder_label = ttk.Label(toolbar, text="未选择文件夹")
        self.source_folder_label.pack(side=tk.LEFT, padx=10)
        
        # 主内容区域
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 左侧：图片预览和操作
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        
        # 使用PanedWindow来更好地控制空间分配
        self.left_paned = ttk.PanedWindow(left_frame, orient=tk.HORIZONTAL)
        self.left_paned.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 绑定sash移动事件，防止用户将分割线拖到不合理位置
        def on_sash_moved(event):
            # 延迟检查，避免在拖动过程中频繁调用
            if hasattr(self, '_sash_moved_scheduled'):
                self.root.after_cancel(self._sash_moved_scheduled)
            self._sash_moved_scheduled = self.root.after(100, self.maintain_sash_position)
        
        # 注意：ttk.PanedWindow没有直接的sash移动事件，我们需要通过其他方式监控
        # 在窗口完全显示后再设置初始位置
        self.root.after(300, self.maintain_sash_position)
        
        # 上半部分：图片预览和信息
        top_section = ttk.Frame(self.left_paned)
        self.left_paned.add(top_section, weight=1)
        
        # 上半部分：图片预览与信息
        preview_label = ttk.Label(top_section, text="图片预览", font=("Arial", 14, "bold"))
        preview_label.pack(pady=5)
        self.image_canvas = tk.Canvas(top_section, bg="white", width=600, height=400, cursor="hand2")
        self.image_canvas.pack(fill=tk.BOTH, expand=True, pady=5)
        self.image_canvas.bind("<Button-1>", self.show_full_image)
        self.image_canvas.bind("<Enter>", lambda e: self.image_canvas.config(cursor="hand2"))
        self.image_canvas.bind("<Leave>", lambda e: self.image_canvas.config(cursor=""))
        hint_label = ttk.Label(top_section, text="💡 点击图片查看大图", font=("Arial", 9), foreground="gray")
        hint_label.pack()
        self.video_controls_frame = ttk.Frame(top_section)
        self.video_play_btn = ttk.Button(self.video_controls_frame, text="播放", command=self.toggle_video_play)
        self.video_play_btn.pack(side=tk.LEFT, padx=5)
        self.video_seek_var = tk.DoubleVar(value=0)
        self.video_seek = ttk.Scale(self.video_controls_frame, orient='horizontal', variable=self.video_seek_var, command=lambda v: self.on_media_seek(v))
        self.video_seek.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.video_time_label = ttk.Label(self.video_controls_frame, text="00:00 / 00:00")
        self.video_time_label.pack(side=tk.LEFT, padx=5)
        info_frame = ttk.LabelFrame(top_section, text="图片信息")
        info_frame.pack(fill=tk.X, pady=5)
        self.info_label = ttk.Label(info_frame, text="未选择图片", wraplength=700, font=("Arial", 10))
        self.info_label.pack(padx=5, pady=5)

        # 下半部分：分类与操作（垂直布局）
        bottom_container = ttk.Frame(self.left_paned)
        self.left_paned.add(bottom_container, weight=1)
        # 操作按钮区域 - 固定在bottom_container底部，不在滚动区域内
        button_frame = ttk.LabelFrame(bottom_container, text="操作 (快捷键: 空格=下一张)")
        # 分类信息区域（可滚动）
        classification_container = ttk.Frame(bottom_container)
        
        bottom_canvas, bottom_scrollbar, bottom_section = self._create_scrollable_frame(classification_container)

        bottom_window_id = bottom_canvas.find_all()[0] if bottom_canvas.find_all() else None

        def on_bottom_canvas_configure(event):
            min_height = 650
            target_height = max(event.height, min_height)
            bottom_canvas.itemconfig(bottom_window_id, width=event.width, height=target_height)
        bottom_canvas.bind('<Configure>', on_bottom_canvas_configure)

        bottom_canvas.pack(side="left", fill="both", expand=True)
        bottom_scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮事件（只在canvas区域内有效）
        def on_mousewheel(event):
            # 检查鼠标是否在canvas区域内
            if bottom_canvas.winfo_containing(event.x_root, event.y_root) == bottom_canvas:
                bottom_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        bottom_canvas.bind("<MouseWheel>", on_mousewheel)
        bottom_section.bind("<MouseWheel>", on_mousewheel)
        
        # 设置初始分割位置，确保下半部分有足够空间
        # 延迟设置，等待窗口渲染完成，多次尝试确保成功
        def set_initial_sash(attempt=0):
            try:
                self.left_paned.update_idletasks()
                height = self.left_paned.winfo_height()
                if height > 0:
                    sash_pos = int(height * 0.65)
                    self.left_paned.sashpos(0, sash_pos)
                    actual_pos = self.left_paned.sashpos(0)
                    if actual_pos is None or abs(actual_pos - sash_pos) > 10:
                        if attempt < 3:
                            self.root.after(100, lambda: set_initial_sash(attempt + 1))
                elif attempt < 5:
                    self.root.after(100, lambda: set_initial_sash(attempt + 1))
            except Exception:
                if attempt < 3:
                    self.root.after(100, lambda: set_initial_sash(attempt + 1))
        self.root.after(100, lambda: set_initial_sash(0))
        
        # 分类信息选择区域
        classification_frame = ttk.LabelFrame(bottom_section, text="分类信息")
        classification_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        preset_frame = ttk.LabelFrame(classification_frame, text="预制选项")
        preset_frame.pack(fill=tk.X, expand=False, padx=5, pady=(5, 0))
        self.image_preset_combo = ttk.Combobox(
            preset_frame,
            textvariable=self.image_preset_var,
            state="readonly",
            width=28
        )
        self.image_preset_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        self.image_preset_combo.bind("<<ComboboxSelected>>", self.apply_selected_image_preset)
        ttk.Button(preset_frame, text="保存为预制", command=self.save_current_image_preset).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(preset_frame, text="覆盖当前预制", command=self.overwrite_current_image_preset).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(preset_frame, text="管理预制", command=self.open_image_preset_manager).pack(side=tk.LEFT, padx=5, pady=5)
        
        # 模特选择区域
        model_select_frame = ttk.LabelFrame(classification_frame, text="选择模特（单选）")
        model_select_frame.pack(fill=tk.BOTH, expand=False, padx=5, pady=5)
        
        self.model_canvas, model_scrollbar, self.model_scrollable_frame = self._create_scrollable_frame(model_select_frame)
        self.model_canvas.configure(height=80)

        self.model_window_id = self.model_canvas.find_all()[0] if self.model_canvas.find_all() else None

        def on_model_canvas_configure(event):
            self.model_canvas.itemconfig(self.model_window_id, width=event.width)
        self.model_canvas.bind('<Configure>', on_model_canvas_configure)

        self.model_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        model_scrollbar.pack(side="right", fill="y")
        
        # 存储模特单选按钮变量（改为单选）
        self.model_var = tk.StringVar()  # 用于单选，存储选中的模特ID
        
        # 标签选择区域
        tag_select_frame = ttk.LabelFrame(classification_frame, text="选择标签（可多选）")
        tag_select_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(12, 5))
        
        self.tag_canvas, tag_scrollbar, self.tag_scrollable_frame = self._create_scrollable_frame(tag_select_frame)
        self.tag_canvas.configure(height=560)

        self.tag_window_id = self.tag_canvas.find_all()[0] if self.tag_canvas.find_all() else None

        def on_tag_canvas_configure(event):
            self.tag_canvas.itemconfig(self.tag_window_id, width=event.width)
        self.tag_canvas.bind('<Configure>', on_tag_canvas_configure)

        self.tag_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        tag_scrollbar.pack(side="right", fill="y")

        # 去除自适应高度的持续调整，交由pack(expand=True)自然填充，避免循环增长
        
        # 存储标签复选框变量
        self.tag_vars = {}
        
        # 先pack按钮区域（固定在底部），确保始终可见
        button_frame.pack(fill=tk.X, pady=(5, 0), side=tk.BOTTOM)
        
        # 然后pack分类信息区域（占用剩余空间）
        classification_container.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # 保存按钮区域 - 更明显的样式
        save_button_frame = ttk.Frame(button_frame)
        save_button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # 保存按钮 — 统一执行：保存标签→移动文件→自动下一张
        save_image_button = tk.Button(
            save_button_frame,
            text="💾 保存并归档 (S)",
            command=self.save_image,
            bg="#4CAF50",
            fg="white",
            font=("Arial", 11, "bold"),
            relief=tk.RAISED,
            bd=3,
            cursor="hand2"
        )
        save_image_button.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, ipady=5)

        # 加入黑名单按钮
        blacklist_button = tk.Button(
            save_button_frame,
            text="🚫 丢弃到黑名单",
            command=self.add_to_blacklist,
            bg="#F44336",
            fg="white",
            font=("Arial", 11, "bold"),
            relief=tk.RAISED,
            bd=3,
            cursor="hand2"
        )
        blacklist_button.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, ipady=5)
        
        # 其他操作按钮
        other_button_frame = ttk.Frame(button_frame)
        other_button_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(other_button_frame, text="上一张 (←)", command=self.load_previous).pack(side=tk.LEFT, padx=5)
        ttk.Button(other_button_frame, text="下一张 (→)", command=self.load_next).pack(side=tk.LEFT, padx=5)
        
        # 右侧：文件列表（窄栏）
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=5)
        right_frame.config(width=250)
        
        # 文件列表
        list_frame = ttk.LabelFrame(right_frame, text="待处理图片列表")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 文件列表
        list_container = ttk.Frame(list_frame)
        list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(list_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.file_listbox = tk.Listbox(list_container, yscrollcommand=scrollbar.set, font=("Arial", 10), exportselection=False)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_listbox.bind('<<ListboxSelect>>', self.on_file_select)
        scrollbar.config(command=self.file_listbox.yview)
        
        # 状态栏
        self.status_label = ttk.Label(self.root, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(fill=tk.X, side=tk.BOTTOM)
        self.refresh_image_preset_controls()
    
    def bind_shortcuts(self):
        """绑定键盘快捷键 — 保留图片处理核心快捷键"""
        self.root.bind('<Key-space>', lambda e: self.load_next())
        self.root.bind('<Key-Left>', lambda e: self.load_previous())
        self.root.bind('<Key-Right>', lambda e: self.load_next())
        self.root.bind('<Control-a>', lambda e: self.load_previous())
        self.root.bind('<Control-A>', lambda e: self.load_previous())
        self.root.bind('<Control-d>', lambda e: self.load_next())
        self.root.bind('<Control-D>', lambda e: self.load_next())
        self.root.bind('<Key-s>', lambda e: self.save_image())
        self.root.bind('<Key-S>', lambda e: self.save_image())
        self.root.bind_all('<Control-MouseWheel>', self.on_global_preset_mousewheel, add='+')
        self.root.bind('<Configure>', lambda e: self.on_window_configure(e))
        self.root.focus_set()
    
    def on_window_configure(self, event):
        """窗口大小变化时的处理"""
        # 只在主窗口大小变化时处理（避免处理子组件的事件）
        if event.widget == self.root:
            # 延迟处理，避免频繁调用
            if hasattr(self, '_sash_check_scheduled'):
                self.root.after_cancel(self._sash_check_scheduled)
            self._sash_check_scheduled = self.root.after(200, self.maintain_sash_position)
    
    def select_source_folder(self):
        """选择源文件夹"""
        folder = filedialog.askdirectory(title="选择包含图片的文件夹")
        if folder:
            self.file_manager.set_source_folder(folder)
            self.source_folder_label.config(text=f"源: {os.path.basename(folder)}")
            self.scan_folder()
            # 自动加载第一张图片
            if self.image_files:
                self.load_image_by_index(0)
    
    def scan_folder(self):
        """扫描文件夹中的媒体文件"""
        files = self.file_manager.get_image_files()
        filtered = [p for p in files if not self.is_video_path(p)]
        try:
            self.image_files = sorted(filtered, key=functools.cmp_to_key(lambda a, b: _win_logical_cmp(os.path.basename(a), os.path.basename(b))))
        except Exception:
            self.image_files = sorted(filtered, key=lambda p: os.path.basename(p).lower())
        self.file_listbox.delete(0, tk.END)
        for img_file in self.image_files:
            self.file_listbox.insert(tk.END, os.path.basename(img_file))
        self.status_label.config(text=f"共 {len(self.image_files)} 个文件")
        self.current_image_index = -1

    def refresh_and_load_next(self):
        """刷新待处理列表并自动加载下一张图片"""
        # 保存当前索引
        current_index = self.current_image_index
        
        # 刷新列表（文件被移动后，会从列表中移除）
        self.scan_folder()
        
        # 如果列表为空，显示提示并清空显示
        if len(self.image_files) == 0:
            self.status_label.config(text="待处理列表已为空")
            # 清空当前图片显示
            self.current_image_path = None
            self.current_file_id = None
            self.current_image_index = -1
            self.image_canvas.delete("all")
            self.info_label.config(text="")
            # 清空分类选择UI
            for widget in self.model_scrollable_frame.winfo_children():
                widget.destroy()
            for widget in self.tag_scrollable_frame.winfo_children():
                widget.destroy()
            self.model_var.set('')
            self.tag_vars.clear()
            return
        
        # 尝试加载下一张图片
        # 由于当前文件已被移除，原索引对应的就是下一张图片
        next_index = current_index
        
        # 如果原索引超出范围，说明是最后一张，加载最后一张
        if next_index >= len(self.image_files):
            next_index = len(self.image_files) - 1
        
        # 如果索引有效，加载该图片
        if next_index >= 0:
            self.load_image_by_index(next_index)
        else:
            # 如果索引无效，加载第一张
            if len(self.image_files) > 0:
                self.load_image_by_index(0)
    
    def load_image_by_index(self, index):
        """根据索引加载图片"""
        if 0 <= index < len(self.image_files):
            self.current_image_index = index
            self.load_image(self.image_files[index])
            # 更新列表选择
            self.file_listbox.selection_clear(0, tk.END)
            self.file_listbox.selection_set(index)
            self.file_listbox.see(index)
    
    def load_next(self):
        """加载下一张图片"""
        if self.current_image_index < len(self.image_files) - 1:
            self.load_image_by_index(self.current_image_index + 1)
        else:
            self.status_label.config(text="已经是最后一张")
    
    def load_previous(self):
        """加载上一张图片"""
        if self.current_image_index > 0:
            self.load_image_by_index(self.current_image_index - 1)
        else:
            self.status_label.config(text="已经是第一张")
    
    def on_file_select(self, event):
        """选择文件时的回调"""
        selection = self.file_listbox.curselection()
        if selection:
            index = selection[0]
            self.load_image_by_index(index)
    
    def load_image(self, image_path):
        """加载并显示预览"""
        self.current_image_path = image_path
        
        try:
            if self.is_video_path(image_path):
                self.destroy_video()
                self.destroy_gif()
                self.image_canvas.delete("all")
                cw = self.image_canvas.winfo_width() or 600
                ch = self.image_canvas.winfo_height() or 450
                self.image_canvas.create_text(cw//2, ch//2, text="该文件为视频，请到视频处理页操作", font=("Arial", 12))
                img = None
            elif self.is_gif_path(image_path):
                self.init_gif(image_path)
                img = self.get_preview_image(image_path)
            else:
                self.destroy_video()
                self.destroy_gif()
                img = self.get_preview_image(image_path)
            # 计算合适的显示尺寸
            canvas_width = self.image_canvas.winfo_width()
            canvas_height = self.image_canvas.winfo_height()
            if canvas_width <= 1:
                canvas_width = 600
            if canvas_height <= 1:
                canvas_height = 450
            if img is not None:
                # 检查预加载缓存
                if self._preloaded_path == image_path and self._preloaded_photo is not None:
                    photo = self._preloaded_photo
                    self._preloaded_photo = None
                    self._preloaded_path = None
                    self._preloaded_index = -1
                else:
                    img.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                self.image_canvas.delete("all")
                x = canvas_width // 2
                y = canvas_height // 2
                self.image_canvas.create_image(x, y, image=photo, anchor=tk.CENTER)
                self.image_canvas.image = photo
            
            # 获取文件记录（不自动创建）
            file_record = self.db.get_file(image_path)
            if file_record:
                self.current_file_id = file_record['id']
            else:
                # 不自动创建，等待用户点击保存按钮
                self.current_file_id = None
            
            # 更新信息
            self.update_image_info()
            
            # 强制刷新界面，确保图片显示
            self.root.update_idletasks()
            
            # 确保PanedWindow的分割位置保持在合理位置（防止被压缩）
            # 延迟执行，确保界面完全渲染后再调整
            self.root.after(50, self.maintain_sash_position)
            self.root.after(200, self.maintain_sash_position)  # 双重保险
            
            # 确保焦点在窗口上以便使用快捷键
            # 更新状态栏
            self.status_label.config(text=f"进度: {self.current_image_index + 1} / {len(self.image_files)}")
            # 预加载下一张图片
            self.root.after(80, self._preload_next_image)
            self.root.focus_set()

        except Exception as e:
            messagebox.showerror("错误", f"加载预览失败: {str(e)}")

    def get_preview_image(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in self.VIDEO_EXTENSIONS:
            cap = cv2.VideoCapture(path)
            ok, frame = cap.read()
            cap.release()
            if not ok or frame is None:
                raise RuntimeError("无法读取视频帧")
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return Image.fromarray(rgb)
        if ext in self.AUDIO_EXTENSIONS:
            img = Image.new('RGB', (640, 360), '#eef6ff')
            d = ImageDraw.Draw(img)
            d.rectangle([(20,20),(620,340)], outline='#cfe2ff', width=2)
            d.text((320, 180), '♪', anchor='mm', fill='#2563eb', align='center')
            return img
        with Image.open(path) as img:
            return img.copy()

    def is_video_path(self, path):
        ext = os.path.splitext(path)[1].lower()
        return ext in self.VIDEO_EXTENSIONS | self.AUDIO_EXTENSIONS

    def is_gif_path(self, path):
        return os.path.splitext(path)[1].lower() == '.gif'

    def _preload_next_image(self):
        """预加载下一张图片到缓存，减少翻页延迟"""
        try:
            next_idx = self.current_image_index + 1
            if next_idx >= len(self.image_files):
                self._preloaded_photo = None
                self._preloaded_index = -1
                self._preloaded_path = None
                return
            next_path = self.image_files[next_idx]
            if self.is_video_path(next_path):
                return
            canvas_width = self.image_canvas.winfo_width()
            canvas_height = self.image_canvas.winfo_height()
            if canvas_width <= 1:
                canvas_width = 600
            if canvas_height <= 1:
                canvas_height = 450
            img = self.get_preview_image(next_path)
            img.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)
            self._preloaded_photo = ImageTk.PhotoImage(img)
            self._preloaded_index = next_idx
            self._preloaded_path = next_path
        except Exception:
            self._preloaded_photo = None
            self._preloaded_index = -1
            self._preloaded_path = None

    def _create_scrollable_frame(self, parent):
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        return canvas, scrollbar, inner

    def init_video(self, path):
        self.destroy_video()
        self.destroy_gif()
        self.video_cap = cv2.VideoCapture(path)
        self.video_total_frames = int(self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(self.video_cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.video_fps = fps if fps and fps > 0 else 25.0
        self.video_playing = False
        self.video_seek_var.set(0)
        self.video_seek.configure(from_=0, to=max(self.video_total_frames - 1, 0))
        self.video_play_btn.config(text="播放")
        self.video_time_label.config(text=self.format_time_label(0, self.video_total_frames, self.video_fps))
        self.video_controls_frame.pack(fill=tk.X, pady=5)
        self.video_is_video = True

    def destroy_video(self):
        if self.video_after_id:
            try:
                self.root.after_cancel(self.video_after_id)
            except Exception:
                pass
            self.video_after_id = None
        if self.video_cap:
            try:
                self.video_cap.release()
            except Exception:
                pass
            self.video_cap = None
        self.video_playing = False
        try:
            self.video_controls_frame.pack_forget()
        except Exception:
            pass
        self.video_is_video = False

    def init_gif(self, path):
        self.destroy_video()
        self.destroy_gif()
        try:
            img = Image.open(path)
        except Exception as e:
            raise RuntimeError(f"无法打开GIF: {e}")
        total = getattr(img, 'n_frames', 1)
        durations = []
        try:
            for i in range(total):
                img.seek(i)
                durations.append(int(img.info.get('duration', 100)))
            img.seek(0)
        except Exception:
            durations = [100] * total
            try:
                img.seek(0)
            except Exception:
                pass
        self.gif_img = img
        self.gif_total_frames = total
        self.gif_durations_ms = durations
        self.gif_current_index = 0
        self.gif_playing = False
        self.gif_is_gif = True
        self.video_seek_var.set(0)
        self.video_seek.configure(from_=0, to=max(total - 1, 0))
        self.video_play_btn.config(text="播放")
        self.video_time_label.config(text=self.format_time_label_ms(0, sum(self.gif_durations_ms)))
        self.video_controls_frame.pack(fill=tk.X, pady=5)

    def destroy_gif(self):
        if self.gif_after_id:
            try:
                self.root.after_cancel(self.gif_after_id)
            except Exception:
                pass
            self.gif_after_id = None
        if self.gif_img:
            try:
                self.gif_img.close()
            except Exception:
                pass
        self.gif_img = None
        self.gif_playing = False
        self.gif_total_frames = 0
        self.gif_durations_ms = []
        self.gif_current_index = 0
        self.gif_is_gif = False
        try:
            self.video_controls_frame.pack_forget()
        except Exception:
            pass

    def toggle_video_play(self):
        if self.video_is_video:
            self.video_playing = not self.video_playing
            self.video_play_btn.config(text="暂停" if self.video_playing else "播放")
            if self.video_playing:
                self.update_video_frame()
            else:
                if self.video_after_id:
                    try:
                        self.root.after_cancel(self.video_after_id)
                    except Exception:
                        pass
                    self.video_after_id = None
            return
        if self.gif_is_gif:
            self.gif_playing = not self.gif_playing
            self.video_play_btn.config(text="暂停" if self.gif_playing else "播放")
            if self.gif_playing:
                self.update_gif_frame()
            else:
                if self.gif_after_id:
                    try:
                        self.root.after_cancel(self.gif_after_id)
                    except Exception:
                        pass
                    self.gif_after_id = None

    def update_video_frame(self):
        if not self.video_cap:
            return
        ok, frame = self.video_cap.read()
        if not ok or frame is None:
            self.video_playing = False
            self.video_play_btn.config(text="播放")
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        canvas_width = self.image_canvas.winfo_width() or 600
        canvas_height = self.image_canvas.winfo_height() or 450
        img.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self.image_canvas.delete("all")
        x = canvas_width // 2
        y = canvas_height // 2
        self.image_canvas.create_image(x, y, image=photo, anchor=tk.CENTER)
        self.image_canvas.image = photo
        pos = int(self.video_cap.get(cv2.CAP_PROP_POS_FRAMES) or 0)
        self.video_seek_var.set(pos)
        self.video_time_label.config(text=self.format_time_label(pos, self.video_total_frames, self.video_fps))
        if self.video_playing:
            delay = int(1000 / self.video_fps) if self.video_fps > 0 else 40
            self.video_after_id = self.root.after(delay, self.update_video_frame)

    def update_gif_frame(self):
        if not self.gif_img:
            return
        idx = self.gif_current_index
        try:
            self.gif_img.seek(idx)
            frame = self.gif_img.copy()
        except Exception:
            self.gif_playing = False
            self.video_play_btn.config(text="播放")
            return
        if frame.mode not in ("RGB", "RGBA"):
            frame = frame.convert("RGB")
        img = frame
        canvas_width = self.image_canvas.winfo_width() or 600
        canvas_height = self.image_canvas.winfo_height() or 450
        img.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self.image_canvas.delete("all")
        x = canvas_width // 2
        y = canvas_height // 2
        self.image_canvas.create_image(x, y, image=photo, anchor=tk.CENTER)
        self.image_canvas.image = photo
        self.video_seek_var.set(idx)
        elapsed = sum(self.gif_durations_ms[:idx]) if self.gif_durations_ms else 0
        total = sum(self.gif_durations_ms) if self.gif_durations_ms else 0
        self.video_time_label.config(text=self.format_time_label_ms(elapsed, total))
        if self.gif_playing:
            if idx >= self.gif_total_frames - 1:
                self.gif_playing = False
                self.video_play_btn.config(text="播放")
                return
            delay = int(self.gif_durations_ms[idx]) if self.gif_durations_ms else 100
            self.gif_current_index = idx + 1
            self.gif_after_id = self.root.after(max(delay, 1), self.update_gif_frame)

    def on_video_seek(self, value):
        if not self.video_cap:
            return
        try:
            idx = int(float(value))
        except Exception:
            idx = 0
        self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, idx))
        ok, frame = self.video_cap.read()
        if not ok or frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        canvas_width = self.image_canvas.winfo_width() or 600
        canvas_height = self.image_canvas.winfo_height() or 450
        img.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self.image_canvas.delete("all")
        x = canvas_width // 2
        y = canvas_height // 2
        self.image_canvas.create_image(x, y, image=photo, anchor=tk.CENTER)
        self.image_canvas.image = photo
        pos = int(self.video_cap.get(cv2.CAP_PROP_POS_FRAMES) or idx)
        self.video_seek_var.set(pos)
        self.video_time_label.config(text=self.format_time_label(pos, self.video_total_frames, self.video_fps))

    def on_gif_seek(self, value):
        if not self.gif_img:
            return
        try:
            idx = int(float(value))
        except Exception:
            idx = 0
        idx = max(0, min(idx, self.gif_total_frames - 1))
        self.gif_current_index = idx
        try:
            self.gif_img.seek(idx)
            frame = self.gif_img.copy()
        except Exception:
            return
        if frame.mode not in ("RGB", "RGBA"):
            frame = frame.convert("RGB")
        img = frame
        canvas_width = self.image_canvas.winfo_width() or 600
        canvas_height = self.image_canvas.winfo_height() or 450
        img.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self.image_canvas.delete("all")
        x = canvas_width // 2
        y = canvas_height // 2
        self.image_canvas.create_image(x, y, image=photo, anchor=tk.CENTER)
        self.image_canvas.image = photo
        self.video_seek_var.set(idx)
        elapsed = sum(self.gif_durations_ms[:idx]) if self.gif_durations_ms else 0
        total = sum(self.gif_durations_ms) if self.gif_durations_ms else 0
        self.video_time_label.config(text=self.format_time_label_ms(elapsed, total))

    def on_media_seek(self, value):
        if self.video_is_video:
            self.on_video_seek(value)
            return
        if self.gif_is_gif:
            self.on_gif_seek(value)
            return

    def format_time_label(self, pos_frames, total_frames, fps):
        def fmt(t):
            m = int(t // 60)
            s = int(t % 60)
            return f"{m:02d}:{s:02d}"
        cur = pos_frames / fps if fps > 0 else 0
        tot = total_frames / fps if fps > 0 else 0
        return f"{fmt(cur)} / {fmt(tot)}"

    def format_time_label_ms(self, elapsed_ms, total_ms):
        def fmt_ms(ms):
            s = int((ms // 1000) % 60)
            m = int((ms // 1000) // 60)
            return f"{m:02d}:{s:02d}"
        return f"{fmt_ms(elapsed_ms)} / {fmt_ms(total_ms)}"
    
    def show_full_image(self, event=None):
        """显示大图窗口"""
        if not self.current_image_path or not os.path.exists(self.current_image_path):
            messagebox.showwarning("警告", "当前没有可查看的图片")
            return
        
        try:
            # 创建新窗口
            full_image_window = tk.Toplevel(self.root)
            full_image_window.title(f"查看大图 - {os.path.basename(self.current_image_path)}")
            
            img = self.get_preview_image(self.current_image_path)
            original_width, original_height = img.size
            
            # 获取屏幕尺寸
            screen_width = full_image_window.winfo_screenwidth()
            screen_height = full_image_window.winfo_screenheight()
            
            # 计算合适的窗口尺寸（留出边距）
            max_width = int(screen_width * 0.9)
            max_height = int(screen_height * 0.9)
            
            # 如果图片比屏幕小，按原尺寸显示；否则按比例缩放
            if original_width <= max_width and original_height <= max_height:
                display_width = original_width
                display_height = original_height
            else:
                scale = min(max_width / original_width, max_height / original_height)
                display_width = int(original_width * scale)
                display_height = int(original_height * scale)
            
            # 设置窗口大小
            full_image_window.geometry(f"{display_width + 20}x{display_height + 60}")
            
            # 居中显示窗口
            x = (screen_width - display_width - 20) // 2
            y = (screen_height - display_height - 60) // 2
            full_image_window.geometry(f"{display_width + 20}x{display_height + 60}+{x}+{y}")
            
            # 创建Canvas显示图片
            canvas = tk.Canvas(full_image_window, width=display_width, height=display_height, bg="white")
            canvas.pack(padx=10, pady=10)
            
            # 缩放图片
            if display_width != original_width or display_height != original_height:
                img = img.resize((display_width, display_height), Image.Resampling.LANCZOS)
            
            # 显示图片
            photo = ImageTk.PhotoImage(img)
            canvas.create_image(display_width // 2, display_height // 2, image=photo, anchor=tk.CENTER)
            canvas.image = photo  # 保持引用
            
            # 添加信息标签
            info_text = f"尺寸: {original_width} x {original_height} 像素 | 文件: {os.path.basename(self.current_image_path)}"
            info_label = ttk.Label(full_image_window, text=info_text, font=("Arial", 9))
            info_label.pack(pady=5)
            
            # 添加关闭按钮
            close_button = ttk.Button(full_image_window, text="关闭 (ESC)", command=full_image_window.destroy)
            close_button.pack(pady=5)
            
            # 绑定ESC键关闭窗口
            full_image_window.bind("<Escape>", lambda e: full_image_window.destroy())
            full_image_window.focus_set()
            
        except Exception as e:
            messagebox.showerror("错误", f"打开大图失败: {str(e)}")

    def open_video_processor(self):
        if self.current_dialog is not None:
            try:
                self.current_dialog.lift()
                self.current_dialog.focus_force()
                return
            except Exception:
                self.current_dialog = None
        vp = tk.Toplevel(self.root)
        vp.title("视频处理")
        vp.geometry("1100x700")
        try:
            vp.state('zoomed')
        except Exception:
            try:
                sw = vp.winfo_screenwidth()
                sh = vp.winfo_screenheight()
                vp.geometry(f"{sw}x{sh}+0+0")
            except Exception:
                pass
        vp.transient(self.root)
        self.current_dialog = vp
        prev_source_folder = getattr(self.file_manager, 'source_folder', None)
        def on_close():
            self.current_dialog = None
            if self.video_preset_context and self.video_preset_context.get('window') == vp:
                self.video_preset_context = None
            vp.destroy()
            self.file_manager.set_source_folder(prev_source_folder)
        vp.protocol("WM_DELETE_WINDOW", on_close)
        self.file_manager.set_source_folder(None)

        main_frame = ttk.Frame(vp)
        main_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)

        left_frame = ttk.LabelFrame(main_frame, text="待处理视频")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,5))
        left_frame.config(width=320)
        try:
            left_frame.pack_propagate(False)
        except Exception:
            pass
        # 顶部源文件夹选择与刷新
        top_left_controls = ttk.Frame(left_frame)
        top_left_controls.pack(fill=tk.X, padx=5, pady=5)
        folder_label = ttk.Label(top_left_controls, text="未选择文件夹")
        folder_label.pack(side=tk.LEFT, padx=5)
        ttk.Button(top_left_controls, text="选择视频文件夹", command=lambda: choose_video_folder()).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_left_controls, text="刷新列表", command=lambda: refresh_video_list()).pack(side=tk.LEFT, padx=5)
        # 搜索
        search_entry = ttk.Entry(left_frame)
        search_entry.pack(fill=tk.X, padx=5, pady=5)
        video_listbox = tk.Listbox(left_frame, exportselection=False)
        video_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        center_frame = ttk.LabelFrame(main_frame, text="选择缩略图（点击选择其中一张作为封面）")
        center_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        center_frame.config(width=520)
        try:
            center_frame.pack_propagate(False)
        except Exception:
            pass
        video_canvas = tk.Canvas(center_frame, bg="black", height=360)
        video_canvas.pack(fill=tk.X, padx=5, pady=(5,0))
        video_controls = ttk.Frame(center_frame)
        video_controls.pack(fill=tk.X, padx=5, pady=(0,5))
        video_play_btn = ttk.Button(video_controls, text="播放")
        video_play_btn.pack(side=tk.LEFT, padx=5)
        vp_video_seek_var = tk.DoubleVar(value=0)
        video_seek = ttk.Scale(video_controls, orient="horizontal", variable=vp_video_seek_var)
        video_seek.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        video_time_label = ttk.Label(video_controls, text="00:00 / 00:00")
        video_time_label.pack(side=tk.LEFT, padx=5)
        vp_state = {"cap": None, "total": 0, "fps": 0.0, "playing": False, "after_id": None, "seek_after_id": None}
        def vp_draw_frame(img):
            canvas_width = video_canvas.winfo_width() or 600
            canvas_height = video_canvas.winfo_height() or 360
            img.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            video_canvas.delete("all")
            x = canvas_width // 2
            y = canvas_height // 2
            video_canvas.create_image(x, y, image=photo, anchor=tk.CENTER)
            video_canvas.image = photo
        def vp_destroy_video():
            if vp_state["seek_after_id"]:
                try:
                    vp.after_cancel(vp_state["seek_after_id"])
                except Exception:
                    pass
                vp_state["seek_after_id"] = None
            if vp_state["after_id"]:
                try:
                    vp.after_cancel(vp_state["after_id"])
                except Exception:
                    pass
                vp_state["after_id"] = None
            if vp_state["cap"]:
                try:
                    vp_state["cap"].release()
                except Exception:
                    pass
                vp_state["cap"] = None
            vp_state["playing"] = False
            video_play_btn.config(text="播放")
        def vp_init_video(path):
            vp_destroy_video()
            cap = cv2.VideoCapture(path)
            vp_state["cap"] = cap
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            vp_state["total"] = total
            vp_state["fps"] = fps if fps and fps > 0 else 25.0
            vp_video_seek_var.set(0)
            try:
                video_seek.configure(from_=0, to=max(total - 1, 0))
            except Exception:
                pass
            video_play_btn.config(text="播放")
            video_time_label.config(text=self.format_time_label(0, total, vp_state["fps"]))
            if total > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = cap.read()
                if ok and frame is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(rgb)
                    vp_draw_frame(img)
        def vp_update_frame():
            if not vp_state["cap"]:
                return
            ok, frame = vp_state["cap"].read()
            if not ok or frame is None:
                vp_state["playing"] = False
                video_play_btn.config(text="播放")
                return
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            vp_draw_frame(img)
            pos = int(vp_state["cap"].get(cv2.CAP_PROP_POS_FRAMES) or 0)
            vp_video_seek_var.set(pos)
            video_time_label.config(text=self.format_time_label(pos, vp_state["total"], vp_state["fps"]))
            if vp_state["playing"]:
                delay = int(1000 / vp_state["fps"]) if vp_state["fps"] > 0 else 40
                vp_state["after_id"] = vp.after(delay, vp_update_frame)
        def vp_toggle_play():
            vp_state["playing"] = not vp_state["playing"]
            video_play_btn.config(text="暂停" if vp_state["playing"] else "播放")
            if vp_state["playing"]:
                vp_update_frame()
            else:
                if vp_state["after_id"]:
                    try:
                        vp.after_cancel(vp_state["after_id"])
                    except Exception:
                        pass
                    vp_state["after_id"] = None
        def vp_on_seek(value):
            if not vp_state["cap"]:
                return
            try:
                pos = int(float(value))
            except Exception:
                pos = int(vp_video_seek_var.get() or 0)
            pos = max(0, min(vp_state["total"] - 1, pos))
            vp_video_seek_var.set(pos)
            if vp_state["seek_after_id"]:
                try:
                    vp.after_cancel(vp_state["seek_after_id"])
                except Exception:
                    pass
                vp_state["seek_after_id"] = None
            def do_seek(p=pos):
                if not vp_state["cap"]:
                    return
                vp_state["cap"].set(cv2.CAP_PROP_POS_FRAMES, p)
                if vp_state["playing"]:
                    video_time_label.config(text=self.format_time_label(p, vp_state["total"], vp_state["fps"]))
                else:
                    ok, frame = vp_state["cap"].read()
                    if ok and frame is not None:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(rgb)
                        vp_draw_frame(img)
                        video_time_label.config(text=self.format_time_label(p, vp_state["total"], vp_state["fps"]))
                vp_state["seek_after_id"] = None
            vp_state["seek_after_id"] = vp.after(75, do_seek)
        video_seek.configure(command=lambda v: vp_on_seek(v))
        video_play_btn.configure(command=vp_toggle_play)
        thumbs_canvas = tk.Canvas(center_frame)
        thumbs_scroll_y = ttk.Scrollbar(center_frame, orient="vertical", command=thumbs_canvas.yview)
        thumbs_scroll_x = ttk.Scrollbar(center_frame, orient="horizontal", command=thumbs_canvas.xview)
        thumbs_inner = ttk.Frame(thumbs_canvas)
        thumbs_canvas.create_window((0,0), window=thumbs_inner, anchor="nw")
        thumbs_canvas.configure(yscrollcommand=thumbs_scroll_y.set, xscrollcommand=thumbs_scroll_x.set)
        thumbs_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=(5,0))
        thumbs_scroll_y.pack(fill=tk.Y, side=tk.RIGHT, padx=0, pady=(5,0))
        thumbs_scroll_x.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=(0,5))

        right_frame = ttk.LabelFrame(main_frame, text="分类信息")
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5,0))

        preset_frame = ttk.LabelFrame(right_frame, text="预制选项")
        preset_frame.pack(fill=tk.X, padx=5, pady=5)
        video_preset_var = tk.StringVar(value="")
        video_preset_combo = ttk.Combobox(preset_frame, textvariable=video_preset_var, state="readonly", width=28)
        video_preset_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        video_preset_state = {"cache": {"items": [], "by_name": {}, "by_id": {}}}

        # 模特单选
        model_frame = ttk.LabelFrame(right_frame, text="选择模特（单选）")
        model_frame.pack(fill=tk.X, padx=5, pady=5)
        model_canvas, model_scrollbar, model_scrollable = self._create_scrollable_frame(model_frame)
        model_canvas.configure(height=44)
        model_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        model_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        selected_model = tk.StringVar()

        # 标签多选
        tag_frame = ttk.LabelFrame(right_frame, text="选择标签（多选）")
        tag_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        tag_canvas, tag_scrollbar, tag_scrollable = self._create_scrollable_frame(tag_frame)
        tag_canvas.configure(height=1120)
        tag_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tag_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tag_vars = {}

        # 底部操作按钮（仅保留关闭）
        bottom_frame = ttk.Frame(vp)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
        def refresh_thumbs():
            sel = video_listbox.curselection()
            if not sel:
                messagebox.showwarning("警告", "请先选择一个视频")
                return
            idx = sel[0]
            if idx >= len(displayed_videos):
                return
            path = displayed_videos[idx]
            generate_thumbnails(path)
        # 预览图下方工具栏（刷新/保存）
        thumbs_toolbar = ttk.Frame(center_frame)
        thumbs_toolbar.pack(fill=tk.X, padx=5, pady=(0,5))
        refresh_btn = ttk.Button(thumbs_toolbar, text="刷新预览图", command=refresh_thumbs)
        refresh_btn.pack(side=tk.LEFT, padx=5)
        ttk.Label(thumbs_toolbar, text="范围(分钟)").pack(side=tk.LEFT, padx=(10,2))
        sample_range_var = tk.StringVar(value="5")
        sample_range_combo = ttk.Combobox(thumbs_toolbar, textvariable=sample_range_var, values=["3","5","10"], width=4, state="readonly")
        sample_range_combo.pack(side=tk.LEFT, padx=(0,8))
        ttk.Label(thumbs_toolbar, text="起点%").pack(side=tk.LEFT, padx=(10,2))
        start_pct_var = tk.StringVar(value="0")
        start_pct_combo = ttk.Combobox(thumbs_toolbar, textvariable=start_pct_var, values=["0","5","10","15","20","30","40","50","60","70","80","90"], width=4, state="readonly")
        start_pct_combo.pack(side=tk.LEFT, padx=(0,8))
        ttk.Label(thumbs_toolbar, text="终点%").pack(side=tk.LEFT, padx=(10,2))
        end_pct_var = tk.StringVar(value="100")
        end_pct_combo = ttk.Combobox(thumbs_toolbar, textvariable=end_pct_var, values=["10","20","30","40","50","60","70","80","90","95","100"], width=4, state="readonly")
        end_pct_combo.pack(side=tk.LEFT, padx=(0,8))
        ttk.Label(thumbs_toolbar, text="数量").pack(side=tk.LEFT, padx=(10,2))
        sample_count_var = tk.IntVar(value=18)
        sample_count_combo = ttk.Combobox(thumbs_toolbar, textvariable=sample_count_var, values=[12,18,24,36,48,72], width=4, state="readonly")
        sample_count_combo.pack(side=tk.LEFT, padx=(0,8))
        ttk.Label(thumbs_toolbar, text="模式").pack(side=tk.LEFT, padx=(10,2))
        sample_mode_var = tk.StringVar(value="场景")
        sample_mode_combo = ttk.Combobox(thumbs_toolbar, textvariable=sample_mode_var, values=["均匀","场景"], width=6, state="readonly")
        sample_mode_combo.pack(side=tk.LEFT, padx=(0,8))
        save_btn = ttk.Button(thumbs_toolbar, text="保存视频与缩略图")
        save_btn.pack(side=tk.LEFT, padx=5)
        stop_btn = ttk.Button(thumbs_toolbar, text="停止生成")
        stop_btn.pack(side=tk.LEFT, padx=5)
        auto_host_var = tk.BooleanVar(value=False)
        def toggle_auto_host():
            v = not bool(auto_host_var.get())
            auto_host_var.set(v)
            try:
                auto_btn.config(text=("取消托管" if v else "自动托管"))
            except Exception:
                pass
        auto_btn = ttk.Button(thumbs_toolbar, text="自动托管", command=toggle_auto_host)
        auto_btn.pack(side=tk.LEFT, padx=5)
        gen_label = ttk.Label(thumbs_toolbar, text="")
        gen_label.pack(side=tk.LEFT, padx=8)
        cancel_btn = ttk.Button(bottom_frame, text="关闭", command=on_close)
        cancel_btn.pack(side=tk.RIGHT, padx=5)

        displayed_videos = []
        thumbs_photos = []
        thumbs_images = []
        thumb_widgets = []  # [{canvas: Canvas}]
        selected_thumb_index = {'idx': 0}
        gen_state = {"cap": None, "positions": [], "i": 0, "cancel": False, "after_id": None, "busy": False, "q": None, "thread": None, "done": False, "expected": 0, "received": 0}

        def refresh_video_preset_controls():
            cache = self._load_presets('video')
            video_preset_state["cache"] = cache
            names = [''] + [item['name'] for item in cache['items']]
            video_preset_combo['values'] = names
            if video_preset_var.get() not in cache['by_name']:
                video_preset_var.set('')

        def apply_selected_video_preset(event=None):
            name = (video_preset_var.get() or '').strip()
            if not name:
                return
            cache = video_preset_state["cache"] or self._load_presets('video')
            preset = cache['by_name'].get(name)
            if not preset:
                messagebox.showerror("错误", "未找到选中的视频预制", parent=vp)
                refresh_video_preset_controls()
                return
            try:
                full_preset = self.db.get_preset('video', preset['preset_id'])
                if not full_preset:
                    raise ValueError("预制不存在或已删除")
                self._apply_preset_tags_to_vars('video', full_preset, tag_vars=tag_vars)
                gen_label.config(text=f"已应用预制：{full_preset['name']}")
            except Exception as e:
                messagebox.showerror("错误", f"应用预制失败：\n{str(e)}", parent=vp)
                refresh_video_preset_controls()

        def on_video_preset_mousewheel(event):
            if not (event.state & 0x0004):
                return None
            step = -1 if event.delta > 0 else 1
            self._cycle_preset_selection(
                video_preset_var,
                'video',
                step,
                lambda: apply_selected_video_preset(),
                combo=video_preset_combo,
            )
            return "break"

        def save_current_video_preset():
            tag_ids = self._get_selected_tag_ids(tag_vars)
            if not tag_ids:
                messagebox.showwarning("警告", "请先勾选至少一个标签", parent=vp)
                return
            name = simpledialog.askstring("保存为预制", "请输入视频预制名称（50字内）:", parent=vp)
            if name is None:
                return
            try:
                preset_id = self.db.create_preset('video', name=name, sort_order=len(video_preset_state["cache"].get('items', [])), tags=tag_ids)
                refresh_video_preset_controls()
                preset = self.db.get_preset('video', preset_id)
                if preset:
                    video_preset_var.set(preset['name'])
                gen_label.config(text=f"视频预制已保存：{name.strip()}")
            except Exception as e:
                messagebox.showerror("错误", f"保存预制失败：\n{str(e)}", parent=vp)

        def overwrite_current_video_preset():
            try:
                updated = self._overwrite_selected_preset(
                    'video',
                    video_preset_var.get(),
                    self._get_selected_tag_ids(tag_vars),
                    parent=vp,
                    tag_vars=tag_vars,
                )
                if updated:
                    refresh_video_preset_controls()
                    video_preset_var.set(updated['name'])
                    gen_label.config(text=f"视频预制已覆盖：{updated['name']}")
            except Exception as e:
                messagebox.showerror("错误", f"覆盖预制失败：\n{str(e)}", parent=vp)

        ttk.Button(preset_frame, text="保存为预制", command=save_current_video_preset).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(preset_frame, text="覆盖当前预制", command=overwrite_current_video_preset).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(
            preset_frame,
            text="管理预制",
            command=lambda: self.open_preset_manager('video', parent=vp, on_change=refresh_video_preset_controls)
        ).pack(side=tk.LEFT, padx=5, pady=5)
        video_preset_combo.bind('<<ComboboxSelected>>', apply_selected_video_preset)
        self.video_preset_context = {
            "window": vp,
            "var": video_preset_var,
            "combo": video_preset_combo,
            "apply": lambda: apply_selected_video_preset(),
        }

        def load_models_tags():
            for w in model_scrollable.winfo_children():
                w.destroy()
            for w in tag_scrollable.winfo_children():
                w.destroy()
            models = self.db.get_active_models()
            for m in models:
                rb = ttk.Radiobutton(model_scrollable, text=m['name'], variable=selected_model, value=m['id'])
                rb.pack(anchor=tk.W, padx=5, pady=2)
            if self.last_selected_model_id:
                selected_model.set(self.last_selected_model_id)
            tags = self.db.get_tags_with_category_name(only_active=False)
            tag_vars.clear()
            groups = {}
            ordered_keys = []
            for t in tags:
                key = t.get('category_id') or 'UNCATEGORIZED'
                if key not in groups:
                    groups[key] = {'name': t.get('category_name') or '未分类', 'tags': []}
                    ordered_keys.append(key)
                groups[key]['tags'].append(t)
            max_cols = 8
            for key in ordered_keys:
                group = groups[key]
                section = ttk.LabelFrame(tag_scrollable, text=group['name'])
                section.pack(fill=tk.X, expand=False, padx=2, pady=2)
                for c in range(max_cols):
                    section.grid_columnconfigure(c, weight=1)
                for i, t in enumerate(group['tags']):
                    v = tk.BooleanVar()
                    if t['id'] in self.last_selected_tag_ids:
                        v.set(True)
                    tag_vars[t['id']] = v
                    cb = ttk.Checkbutton(section, text=t['name'], variable=v)
                    cb.grid(row=i // max_cols, column=i % max_cols, padx=2, pady=1, sticky="w")

        def refresh_video_list():
            video_listbox.delete(0, tk.END)
            displayed_videos.clear()
            files = self.file_manager.get_video_files()
            try:
                files = sorted(files, key=functools.cmp_to_key(lambda a, b: _win_logical_cmp(os.path.basename(a), os.path.basename(b))))
            except Exception:
                files = sorted(files, key=lambda p: os.path.basename(p).lower())
            s = search_entry.get().lower()
            for p in files:
                name = os.path.basename(p)
                if s and s not in (name.lower()+p.lower()):
                    continue
                video_listbox.insert(tk.END, name)
                displayed_videos.append(p)
            # 更新文件夹标签
            cur_folder = getattr(self.file_manager, 'source_folder', None)
            if cur_folder:
                folder_label.config(text=f"源文件夹: {os.path.basename(cur_folder)}")
            else:
                folder_label.config(text="未选择文件夹")

        def choose_video_folder():
            folder = filedialog.askdirectory(title="选择包含视频的文件夹")
            if folder:
                self.file_manager.set_source_folder(folder)
                folder_label.config(text=f"源文件夹: {os.path.basename(folder)}")
                refresh_video_list()

        def generate_thumbnails(path, count=12):
            for w in thumbs_inner.winfo_children():
                w.destroy()
            thumbs_photos.clear()
            thumbs_images.clear()
            thumb_widgets.clear()
            gen_state["cancel"] = False
            gen_state["i"] = 0
            gen_state["busy"] = True
            gen_state["done"] = False
            gen_state["received"] = 0
            gen_state["q"] = queue.Queue(maxsize=8)
            # 音频文件无需生成缩略图，直接跳过
            try:
                ext = os.path.splitext(path)[1].lower()
            except Exception:
                ext = ""
            if ext in {'.mp3', '.m4a'}:
                gen_state["busy"] = False
                gen_state["done"] = True
                gen_state["received"] = 0
                refresh_btn.config(state=tk.NORMAL)
                stop_btn.config(state=tk.DISABLED)
                gen_label.config(text="音频文件无需生成缩略图")
                return
            refresh_btn.config(state=tk.DISABLED)
            stop_btn.config(state=tk.NORMAL)
            cap = cv2.VideoCapture(path)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total <= 0:
                try:
                    cap.release()
                except Exception:
                    pass
                gen_state["busy"] = False
                refresh_btn.config(state=tk.NORMAL)
                stop_btn.config(state=tk.DISABLED)
                gen_label.config(text="")
                return
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            if not fps or fps <= 0:
                fps = 25.0
            fs = 0
            try:
                fs = os.path.getsize(path) if os.path.exists(path) else 0
            except Exception:
                fs = 0
            duration_sec = 0.0
            try:
                duration_sec = float(total) / float(fps) if fps > 0 else 0.0
            except Exception:
                duration_sec = 0.0
            try:
                sp = int(start_pct_var.get()) if start_pct_var.get() else 0
            except Exception:
                sp = 0
            try:
                ep = int(end_pct_var.get()) if end_pct_var.get() else 100
            except Exception:
                ep = 100
            sp = max(0, min(100, sp))
            ep = max(0, min(100, ep))
            if ep <= sp:
                ep = min(100, sp + 5)
            # 采样数量由 UI 指定
            try:
                desired_count = int(sample_count_var.get()) if sample_count_var.get() else count
            except Exception:
                desired_count = count
            desired_count = max(1, min(72, desired_count))
            try:
                import random
                seg_start = max(0, int(total * (sp / 100.0)))
                seg_end = min(total, int(total * (ep / 100.0)))
                margin = max(1, int(fps * 0.5))
                seg_start = min(seg_start + margin, max(0, seg_end - 1))
                seg_end = max(seg_start + 1, seg_end)
                usable = max(1, seg_end - seg_start - margin)
                c = desired_count
                step = max(1, int(usable / c))
                positions = []
                for i in range(c):
                    base = seg_start + i * step
                    jitter = max(1, int(step * 0.15))
                    pos = base + random.randint(-jitter, jitter)
                    positions.append(max(0, min(seg_end - 1, pos)))
            except Exception:
                seg_start = max(0, int(total * (sp / 100.0)))
                seg_end = min(total, int(total * (ep / 100.0)))
                positions = [max(seg_start, min(seg_end - 1, int(seg_start + (i/(desired_count+1)) * (seg_end - seg_start)))) for i in range(1, desired_count+1)]
            try:
                first_pos = 0
                positions = [first_pos] + [p for p in positions if p != first_pos]
                positions = positions[:desired_count]
            except Exception:
                pass
            canvas_w = 180
            canvas_h = 120
            cols = 4
            def draw_selection(canvas):
                canvas.delete('sel_border')
                canvas.create_rectangle(2, 2, canvas_w-2, canvas_h-2, outline='red', width=2, tags='sel_border')
            def clear_selection():
                for tw in thumb_widgets:
                    tw['canvas'].delete('sel_border')
            def make_thumb(idx, frame_img):
                view_img = frame_img.copy()
                view_img.thumbnail((canvas_w-10, canvas_h-10), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(view_img)
                frame = tk.Frame(thumbs_inner, bd=0)
                r = idx // cols
                c = idx % cols
                frame.grid(row=r, column=c, padx=5, pady=5, sticky="n")
                c = tk.Canvas(frame, width=canvas_w, height=canvas_h, bg='white', highlightthickness=0)
                c.pack()
                c.create_image(canvas_w//2, canvas_h//2, image=photo, anchor=tk.CENTER)
                c.image = photo
                def on_click(e=None):
                    selected_thumb_index['idx'] = idx
                    clear_selection()
                    draw_selection(c)
                c.bind('<Button-1>', on_click)
                thumbs_photos.append(photo)
                thumbs_images.append(frame_img)
                thumb_widgets.append({'canvas': c})
            gen_state["positions"] = positions
            gen_state["expected"] = len(positions)
            gen_state["q"] = queue.Queue(maxsize=min(64, max(8, gen_state["expected"])))
            gen_label.config(text=f"生成中 0/{gen_state['expected']}")
            def finish():
                try:
                    cap.release()
                except Exception:
                    pass
                gen_state["cap"] = None
                gen_state["after_id"] = None
                gen_state["busy"] = False
                if thumbs_inner.winfo_children():
                    selected_thumb_index['idx'] = 0
                    if thumb_widgets:
                        draw_selection(thumb_widgets[0]['canvas'])
                try:
                    thumbs_inner.update_idletasks()
                    thumbs_canvas.configure(scrollregion=thumbs_canvas.bbox('all'))
                except Exception:
                    pass
                refresh_btn.config(state=tk.NORMAL)
                stop_btn.config(state=tk.DISABLED)
                gen_label.config(text="")
                try:
                    if auto_host_var.get() and thumbs_images:
                        vp.after(0, lambda: (auto_host_var.get() and save_btn.invoke()))
                except Exception:
                    pass
            def worker():
                try:
                    local_cap = cv2.VideoCapture(path)
                    if not local_cap.isOpened():
                        try:
                            local_cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
                        except Exception:
                            pass
                    accepted = 0
                    prev_small = None
                    mode = (sample_mode_var.get() or "场景").strip()
                    # 阈值随数量调整
                    min_diff = 10 if gen_state["expected"] > 18 else 12
                    for i, pos in enumerate(gen_state["positions"]):
                        if gen_state["cancel"]:
                            break
                        local_cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                        ok, frame = local_cap.read()
                        retry_count = 0
                        while (not ok or frame is None) and retry_count < 2:
                            local_cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                            ok, frame = local_cap.read()
                            retry_count += 1
                        if not ok or frame is None:
                            continue
                        try:
                            h, w = frame.shape[:2]
                            maxw = 1024
                            if w > maxw:
                                scale = maxw / float(w)
                                new_w = int(w * scale)
                                new_h = int(h * scale)
                                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                            if mode == "场景":
                                try:
                                    small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64,64), interpolation=cv2.INTER_AREA)
                                    if prev_small is None:
                                        accept = True
                                    else:
                                        diff = cv2.absdiff(small, prev_small)
                                        mean_diff = float(diff.mean())
                                        accept = mean_diff >= min_diff
                                    if accept:
                                        prev_small = small
                                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                        pil_img = Image.fromarray(rgb)
                                        gen_state["q"].put((i, pil_img))
                                        accepted += 1
                                        if accepted >= gen_state["expected"]:
                                            break
                                    else:
                                        remaining_slots = gen_state["expected"] - accepted
                                        remaining_positions = gen_state["expected"] - (i + 1)
                                        if remaining_slots > remaining_positions:
                                            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                            pil_img = Image.fromarray(rgb)
                                            gen_state["q"].put((i, pil_img))
                                            accepted += 1
                                            if accepted >= gen_state["expected"]:
                                                break
                                        else:
                                            continue
                                except Exception:
                                    # 回退均匀
                                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                    pil_img = Image.fromarray(rgb)
                                    gen_state["q"].put((i, pil_img))
                            else:
                                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                pil_img = Image.fromarray(rgb)
                                gen_state["q"].put((i, pil_img))
                        except Exception:
                            pass
                finally:
                    gen_state["done"] = True
                    try:
                        local_cap.release()
                    except Exception:
                        pass
            def consume():
                consumed = 0
                while consumed < 6:
                    try:
                        i, pil_img = gen_state["q"].get_nowait()
                    except Exception:
                        break
                    make_thumb(i, pil_img)
                    gen_state["received"] += 1
                    consumed += 1
                if gen_state["cancel"] or (gen_state["done"] and gen_state["q"].empty()):
                    finish()
                    return
                gen_label.config(text=f"生成中 {gen_state['received']}/{gen_state['expected']}")
                gen_state["after_id"] = vp.after(30, consume)
            gen_state["thread"] = threading.Thread(target=worker, daemon=True)
            gen_state["thread"].start()
            consume()
        def stop_generate():
            gen_state["cancel"] = True
            stop_btn.config(command=stop_generate)
            gen_label.config(text="正在取消")
            stop_btn.config(state=tk.DISABLED)

        def on_select_video(event=None):
            sel = video_listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            if idx >= len(displayed_videos):
                return
            path = displayed_videos[idx]
            vp_init_video(path)
            generate_thumbnails(path)

        def do_save():
            sel = video_listbox.curselection()
            if not sel:
                messagebox.showwarning("警告", "请先选择一个视频")
                return
            try:
                vp_destroy_video()
            except Exception:
                pass
            if not selected_model.get():
                messagebox.showwarning("警告", "请选择一个模特")
                return
            vid_path = displayed_videos[sel[0]]
            if not thumbs_images:
                try:
                    _, ext = os.path.splitext(vid_path)
                except Exception:
                    ext = ""
                if ext.lower() not in {'.mp3', '.m4a'}:
                    messagebox.showwarning("警告", "请先生成并选择缩略图")
                    return
            model_id = selected_model.get()
            tag_ids = [tid for tid,var in tag_vars.items() if var.get()]
            def save_worker():
                try:
                    file_size = os.path.getsize(vid_path) if os.path.exists(vid_path) else None
                    file_id = self.db.add_file(vid_path, file_name=os.path.basename(vid_path), file_size=file_size)
                    base_folder = os.path.join(get_data_root(),'good', str(model_id))
                    os.makedirs(base_folder, exist_ok=True)
                    subs = []
                    try:
                        subs = [n for n in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, n)) and n.isdigit()]
                    except Exception:
                        subs = []
                    if not subs:
                        sub_name = "001"
                    else:
                        last = sorted(subs)[-1]
                        last_folder = os.path.join(base_folder, last)
                        try:
                            cnt = sum(1 for f in os.listdir(last_folder)
                                      if os.path.isfile(os.path.join(last_folder, f)) and os.path.splitext(f)[1].lower() in self.VIDEO_EXTENSIONS)
                        except Exception:
                            cnt = 0
                        if cnt >= 500:
                            sub_name = f"{int(last)+1:03d}"
                        else:
                            sub_name = last
                    target_folder = os.path.join(base_folder, sub_name)
                    os.makedirs(target_folder, exist_ok=True)
                    _, ext = os.path.splitext(vid_path)
                    new_filename = f"{file_id}{ext}"
                    new_path = os.path.join(target_folder, new_filename)
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    shutil.move(vid_path, new_path)
                    if thumbs_images:
                        idx = selected_thumb_index['idx']
                        if idx < 0 or idx >= len(thumbs_images):
                            idx = 0
                        full_img = thumbs_images[idx]
                        out_img = full_img.copy() if hasattr(full_img, 'copy') else full_img
                        if out_img is None:
                            out_img = thumbs_images[0]
                        if out_img.mode not in ("RGB", "RGBA"):
                            out_img = out_img.convert("RGB")
                        max_w = 1280
                        if out_img.width > max_w or out_img.height > max_w:
                            out_img.thumbnail((max_w, max_w), Image.Resampling.LANCZOS)
                        thumb_filename = f"{file_id}_thumb.jpg"
                        thumb_path = os.path.join(target_folder, thumb_filename)
                        try:
                            out_img.save(thumb_path, format='JPEG', quality=90, optimize=True, progressive=True, subsampling=0)
                        except Exception:
                            out_img.save(thumb_path, format='JPEG', quality=90)
                        self.db.update_file_thumbnail(file_id, thumb_path)
                    self.db.update_file(file_id, file_path=new_path, file_name=new_filename, file_size=os.path.getsize(new_path))
                    try:
                        self.db.save_video_data(file_id, new_path)
                    except Exception:
                        pass
                    self.db.set_file_models(file_id, [model_id])
                    self.db.set_file_tags(file_id, tag_ids)
                    self.last_selected_model_id = model_id
                    current_video_preset = self._restore_current_preset_tags(
                        'video',
                        preset_name=video_preset_var.get(),
                        tag_vars=tag_vars,
                    )
                    if not current_video_preset:
                        self.last_selected_tag_ids = list(tag_ids)
                    def after_success():
                        refresh_video_list()
                        if displayed_videos:
                            next_idx = sel[0]
                            if next_idx >= len(displayed_videos):
                                next_idx = len(displayed_videos) - 1
                            if next_idx >= 0:
                                try:
                                    video_listbox.selection_clear(0, tk.END)
                                    video_listbox.selection_set(next_idx)
                                    video_listbox.activate(next_idx)
                                    video_listbox.see(next_idx)
                                    on_select_video()
                                except Exception:
                                    pass
                        save_btn.config(state=tk.NORMAL)
                    vp.after(0, after_success)
                except Exception as e:
                    err_msg = str(e)
                    def after_fail(msg=err_msg):
                        messagebox.showerror("错误", f"保存失败:\n{msg}")
                        save_btn.config(state=tk.NORMAL)
                    vp.after(0, after_fail)
            save_btn.config(state=tk.DISABLED)
            t = threading.Thread(target=save_worker, daemon=True)
            t.start()

        video_listbox.bind('<<ListboxSelect>>', on_select_video)
        search_entry.bind('<KeyRelease>', lambda e: refresh_video_list())
        save_btn.config(command=do_save)
        # 高亮选中样式
        style = ttk.Style(vp)
        style.configure('Selected.TFrame', bordercolor='blue')
        load_models_tags()
        refresh_video_preset_controls()
        # 初始化文件夹标签显示
        if getattr(self.file_manager, 'source_folder', None):
            folder_label.config(text=f"源文件夹: {os.path.basename(self.file_manager.source_folder)}")
        refresh_video_list()
        def on_close2():
            try:
                vp_destroy_video()
            except Exception:
                pass
            on_close()
        vp.protocol("WM_DELETE_WINDOW", on_close2)
        try:
            cancel_btn.config(command=on_close2)
        except Exception:
            pass
    
    def maintain_sash_position(self):
        """维护PanedWindow的分割位置，确保下半部分始终有足够的可见空间"""
        try:
            if not hasattr(self, 'left_paned'):
                return
            
            self.left_paned.update_idletasks()
            height = self.left_paned.winfo_height()
            
            if height <= 0:
                return
            
            # 获取当前sash位置
            try:
                current_pos = self.left_paned.sashpos(0)
            except Exception:
                current_pos = None
            
            # 计算最小sash位置（确保下半部分至少有35%的空间，至少400像素，保证按钮区域可见）
            min_bottom_height = max(400, int(height * 0.35))  # 下半部分最小高度（像素或35%）
            max_sash_pos = height - min_bottom_height  # sash的最大位置（超过这个位置，下半部分就太小了）
            
            # 如果sash位置无效、太大（下半部分太小）或太小（下半部分太大），调整到合理位置
            needs_adjustment = False
            if current_pos is None:
                needs_adjustment = True
            elif current_pos > max_sash_pos:
                # sash位置太大，下半部分太小
                needs_adjustment = True
            elif current_pos < int(height * 0.50):
                # sash位置太小，下半部分太大（虽然不常见，但也需要调整）
                needs_adjustment = True
            
            if needs_adjustment:
                # 设置目标位置：上半部分65%，下半部分35%
                target_pos = int(height * 0.65)
                target_pos = min(target_pos, max_sash_pos)
                target_pos = max(target_pos, 0)
                
                try:
                    self.left_paned.sashpos(0, target_pos)
                    # 验证设置是否成功
                    self.root.after(50, lambda: self.verify_sash_position(target_pos))
                except Exception as e:
                    # 如果设置失败，稍后重试
                    self.root.after(100, self.maintain_sash_position)
            # 不再维护左右分栏（已恢复垂直布局）
        except Exception as e:
            # 静默处理错误，避免影响主流程
            pass
    
    def verify_sash_position(self, expected_pos):
        try:
            if not hasattr(self, 'left_paned'):
                return
            actual_pos = self.left_paned.sashpos(0)
            if actual_pos is None or abs(actual_pos - expected_pos) > 20:
                self.maintain_sash_position()
        except Exception:
            pass
    
    def update_image_info(self):
        """更新图片信息显示"""
        if not self.current_image_path:
            return
        
        # 更新基本信息
        info_text = f"文件: {os.path.basename(self.current_image_path)}\n"
        info_text += f"路径: {self.current_image_path}\n"
        info_text += f"进度: {self.current_image_index + 1}/{len(self.image_files)}\n"
        
        # 如果文件记录存在，显示更多信息
        if self.current_file_id:
            file_record = self.db.get_file_by_id(self.current_file_id)
            if file_record:
                if file_record['file_size']:
                    size_mb = file_record['file_size'] / (1024 * 1024)
                    info_text += f"大小: {size_mb:.2f} MB\n"
                if file_record.get('file_type'):
                    info_text += f"类型: {file_record.get('file_type')}\n"
                try:
                    w = file_record.get('image_width')
                    h = file_record.get('image_height')
                    if w and h:
                        info_text += f"分辨率: {w}x{h}\n"
                except Exception:
                    pass
                try:
                    vw = file_record.get('video_width')
                    vh = file_record.get('video_height')
                    dur = file_record.get('duration_ms')
                    if vw and vh:
                        info_text += f"视频分辨率: {vw}x{vh}\n"
                    if dur:
                        info_text += f"时长: {self.format_time_label_ms(dur, dur)}\n"
                except Exception:
                    pass
        else:
            # 文件记录不存在，显示未保存状态
            info_text += "状态: 未保存到数据库\n"
        
        self.info_label.config(text=info_text)
        
        # 刷新分类选择UI
        self.refresh_classification_ui()
    
    def refresh_classification_ui(self):
        """刷新分类选择UI"""
        # 清除现有的复选框
        for widget in self.model_scrollable_frame.winfo_children():
            widget.destroy()
        for widget in self.tag_scrollable_frame.winfo_children():
            widget.destroy()
        
        # 清除单选按钮变量（不需要clear，因为使用StringVar）
        self.tag_vars.clear()
        
        if not self.current_image_path:
            return
        
        # 获取有效的模特和标签
        all_models = self.db.get_active_models()
        all_tags = self.db.get_tags_with_category_name(only_active=True)
        
        # 获取当前文件的分类（如果文件记录存在）
        current_model_id = None  # 改为单选，存储单个ID
        current_tag_ids = set()
        if self.current_file_id:
            current_models = self.db.get_file_models(self.current_file_id)
            current_tags = self.db.get_file_tags(self.current_file_id)
            # 如果有模特，取第一个（单选）
            if current_models:
                current_model_id = current_models[0]['id']
            current_tag_ids = {t['id'] for t in current_tags}
        
        # 如果当前图片没有分类，使用上一次的选择
        if not current_model_id and self.last_selected_model_id:
            current_model_id = self.last_selected_model_id
        if not current_tag_ids and self.last_selected_tag_ids:
            current_tag_ids = set(self.last_selected_tag_ids)
        
        # 创建模特单选按钮（横向换行排列）
        max_cols = 4  # 每行最多显示4个
        # 先配置所有列的权重
        for c in range(max_cols):
            self.model_scrollable_frame.grid_columnconfigure(c, weight=1)
        
        row = 0
        col = 0
        for model in all_models:
            radiobutton = ttk.Radiobutton(
                self.model_scrollable_frame, 
                text=model['name'], 
                variable=self.model_var,
                value=model['id']
            )
            radiobutton.grid(row=row, column=col, padx=5, pady=2, sticky="w")
            
            # 设置默认选中
            if model['id'] == current_model_id:
                self.model_var.set(model['id'])
            
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
        
        # 如果没有选中任何模特，且上一次有选择，则选中上一次的
        if not self.model_var.get() and self.last_selected_model_id:
            self.model_var.set(self.last_selected_model_id)
        
        max_cols = 8
        groups = {}
        ordered_keys = []
        for tag in all_tags:
            key = tag.get('category_id') or 'UNCATEGORIZED'
            if key not in groups:
                groups[key] = {'name': tag.get('category_name') or '未分类', 'tags': []}
                ordered_keys.append(key)
            groups[key]['tags'].append(tag)
        for key in ordered_keys:
            group = groups[key]
            section = ttk.LabelFrame(self.tag_scrollable_frame, text=group['name'])
            section.pack(fill=tk.X, expand=False, padx=2, pady=2)
            for c in range(max_cols):
                section.grid_columnconfigure(c, weight=1)
            for i, tag in enumerate(group['tags']):
                var = tk.BooleanVar()
                self.tag_vars[tag['id']] = var
                if tag['id'] in current_tag_ids:
                    var.set(True)
                cb = ttk.Checkbutton(section, text=tag['name'], variable=var)
                cb.grid(row=i // max_cols, column=i % max_cols, padx=2, pady=1, sticky="w")
        
        # 更新Canvas滚动区域
        self.root.update_idletasks()
        if hasattr(self, 'model_canvas'):
            self.model_canvas.configure(scrollregion=self.model_canvas.bbox("all"))
        if hasattr(self, 'tag_canvas'):
            self.tag_canvas.configure(scrollregion=self.tag_canvas.bbox("all"))
    
    def save_classification(self):
        """保存分类信息"""
        if not self.current_image_path:
            messagebox.showwarning("警告", "请先选择一张图片")
            return
        
        # 获取选中的模特（单选）
        selected_model_id = self.model_var.get()
        if not selected_model_id:
            messagebox.showwarning("警告", "请选择一个模特")
            return
        
        # 获取选中的标签
        selected_tag_ids = [tag_id for tag_id, var in self.tag_vars.items() if var.get()]
        
        # 如果文件记录不存在，先创建文件记录
        if not self.current_file_id:
            if not self.current_image_path:
                messagebox.showerror("错误", "无法保存：图片路径不存在")
                return
            self.current_file_id = self.db.add_file(self.current_image_path)
        
        # 保存到数据库（模特改为单个ID的列表）
        self.db.set_file_models(self.current_file_id, [selected_model_id])
        self.db.set_file_tags(self.current_file_id, selected_tag_ids)
        
        # 保存后优先恢复当前预制的标签选择
        self.last_selected_model_id = selected_model_id
        if not self._restore_current_preset_tags('image', preset_name=self.image_preset_var.get()):
            self.last_selected_tag_ids = selected_tag_ids
        
        # 更新显示
        self.update_image_info()
        
        self.status_label.config(text="分类信息已保存")
    
    def save_image(self):
        """保存当前图片到数据库"""
        if not self.current_image_path:
            messagebox.showwarning("警告", "请先选择一张图片")
            return
        
        if not os.path.exists(self.current_image_path):
            messagebox.showerror("错误", "图片文件不存在")
            return
        
        # 检查是否选择了标签和模特
        if not hasattr(self, 'model_var') or not hasattr(self, 'tag_vars'):
            messagebox.showwarning("警告", "请先选择标签和模特")
            return
        
        # 获取选中的模特（单选）
        selected_model_id = self.model_var.get()
        if not selected_model_id:
            messagebox.showwarning("警告", "请选择一个模特")
            return
        selected_model_ids = [selected_model_id]  # 转换为列表以兼容后续代码
        
        # 获取选中的标签
        selected_tag_ids = [tag_id for tag_id, var in self.tag_vars.items() if var.get()]
        
        # 检查是否至少选择了一个标签
        if not selected_tag_ids:
            messagebox.showwarning("警告", "请至少选择一个标签")
            return
        
        try:
            # 如果文件记录不存在，先创建文件记录获取ID
            if not self.current_file_id:
                self.current_file_id = self.db.add_file(self.current_image_path)
            
            # 获取第一个选中的模特ID（用于创建文件夹）
            model_id = selected_model_ids[0]
            
            base_folder = os.path.join(get_data_root(), "good", str(model_id))
            os.makedirs(base_folder, exist_ok=True)
            subs = []
            try:
                subs = [n for n in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, n)) and n.isdigit()]
            except Exception:
                subs = []
            if not subs:
                sub_name = "001"
            else:
                last = sorted(subs)[-1]
                last_folder = os.path.join(base_folder, last)
                try:
                    cnt = sum(1 for f in os.listdir(last_folder) if os.path.isfile(os.path.join(last_folder, f)) and os.path.splitext(f)[1].lower() in (self.IMAGE_EXTENSIONS | self.VIDEO_EXTENSIONS))
                except Exception:
                    cnt = 0
                if cnt >= 1000:
                    sub_name = f"{int(last)+1:03d}"
                else:
                    sub_name = last
            target_folder = os.path.join(base_folder, sub_name)
            os.makedirs(target_folder, exist_ok=True)
            
            # 获取原文件的扩展名
            _, ext = os.path.splitext(self.current_image_path)
            
            # 使用文件ID作为新的文件名
            new_filename = f"{self.current_file_id}{ext}"
            new_file_path = os.path.join(target_folder, new_filename)
            
            # 如果目标文件已存在，添加时间戳
            if os.path.exists(new_file_path) and new_file_path != self.current_image_path:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_filename = f"{self.current_file_id}_{timestamp}{ext}"
                new_file_path = os.path.join(target_folder, new_filename)
            
            # 如果文件不在目标位置，移动文件
            if self.current_image_path != new_file_path:
                # 如果目标文件已存在（同名但不同路径），先删除旧文件
                if os.path.exists(new_file_path):
                    os.remove(new_file_path)
                
                self.destroy_video()
                self.destroy_gif()
                # 移动文件到目标文件夹
                shutil.move(self.current_image_path, new_file_path)
                
                # 更新数据库中的文件路径和文件名
                self.db.update_file(self.current_file_id, file_path=new_file_path, file_name=new_filename)
                
                # 更新当前图片路径
                self.current_image_path = new_file_path
            else:
                # 文件已经在目标位置，确保数据库中的文件名正确
                self.db.update_file(self.current_file_id, file_name=new_filename)
            
            # 计算并保存图片的MD5值到数据库
            self.db.save_image_data(self.current_file_id, new_file_path)
            
            # 保存关联关系（使用 set 方法避免重复）
            self.db.set_file_models(self.current_file_id, selected_model_ids)
            self.db.set_file_tags(self.current_file_id, selected_tag_ids)
            
            # 保存后优先恢复当前预制的标签选择，以便下一张继续沿用该预制
            self.last_selected_model_id = selected_model_id
            if not self._restore_current_preset_tags('image', preset_name=self.image_preset_var.get()):
                self.last_selected_tag_ids = selected_tag_ids
            
            # 在状态栏显示保存成功信息
            self.status_label.config(text=f"✓ 图片已保存！文件ID: {self.current_file_id} | 保存位置: {new_file_path}")
            
            # 保存成功后，刷新待处理列表并自动加载下一张图片
            self.refresh_and_load_next()
            
        except Exception as e:
            messagebox.showerror("错误", f"保存图片失败:\n{str(e)}")
            self.status_label.config(text="保存图片失败")
    
    def add_to_blacklist(self):
        """将当前图片加入黑名单（移动到data/bad文件夹，不写入数据库）"""
        if not self.current_image_path:
            messagebox.showwarning("警告", "请先选择一张图片")
            return
        
        if not os.path.exists(self.current_image_path):
            messagebox.showerror("错误", "图片文件不存在")
            return
        
        # 确认操作
        result = messagebox.askyesno("确认", "确定要将此图片加入黑名单吗？\n文件将被移动到data/bad文件夹，且不会写入数据库。")
        if not result:
            return
        
        try:
            # 确保data/bad文件夹存在
            bad_folder = os.path.join(get_data_root(), "bad")
            os.makedirs(bad_folder, exist_ok=True)
            
            # 获取原文件名
            original_filename = os.path.basename(self.current_image_path)
            
            # 如果文件已经在bad文件夹中，不需要移动
            if os.path.dirname(self.current_image_path) == bad_folder:
                messagebox.showinfo("提示", "文件已在黑名单文件夹中")
                # 刷新列表并加载下一张
                self.refresh_and_load_next()
                return
            
            # 构建目标路径
            target_path = os.path.join(bad_folder, original_filename)
            
            # 如果目标文件已存在，添加时间戳
            if os.path.exists(target_path):
                name, ext = os.path.splitext(original_filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target_path = os.path.join(bad_folder, f"{name}_{timestamp}{ext}")
            
            # 移动文件到黑名单文件夹
            shutil.move(self.current_image_path, target_path)
            
            # 如果文件在数据库中，删除数据库记录
            if self.current_file_id:
                try:
                    self.db.delete_file(self.current_file_id)
                except Exception as e:
                    # 删除数据库记录失败不影响文件移动
                    print(f"删除数据库记录失败: {e}")
            
            # 在状态栏显示成功信息
            self.status_label.config(text=f"✓ 图片已加入黑名单！文件已移动到: {target_path}")
            
            # 刷新列表并自动加载下一张图片
            self.refresh_and_load_next()
            
        except Exception as e:
            messagebox.showerror("错误", f"加入黑名单失败:\n{str(e)}")
            self.status_label.config(text="加入黑名单失败")
    
    def open_model_manager(self):
        """打开模特管理窗口"""
        # 如果已有对话框打开，聚焦到已打开的对话框
        if self.current_dialog is not None:
            try:
                self.current_dialog.lift()
                self.current_dialog.focus_force()
                return
            except Exception:
                # 如果对话框已被销毁，清除引用
                self.current_dialog = None
        
        manager_window = tk.Toplevel(self.root)
        manager_window.title("模特管理")
        manager_window.geometry("1280x860")
        try:
            manager_window.minsize(1100, 700)
        except Exception:
            pass
        manager_window.transient(self.root)
        manager_window.grab_set()
        
        # 记录当前打开的对话框
        self.current_dialog = manager_window
        
        # 对话框关闭时清除引用并刷新分类UI
        def on_close():
            self.current_dialog = None
            manager_window.destroy()
            # 刷新主界面的分类选择UI（如果当前有图片）
            if self.current_image_path:
                self.refresh_classification_ui()
        
        manager_window.protocol("WM_DELETE_WINDOW", on_close)
        
        # 可调整布局：左右三栏可拖拽
        model_pane = ttk.PanedWindow(manager_window, orient=tk.HORIZONTAL)
        model_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧：模特列表和操作
        left_frame = ttk.Frame(model_pane)
        model_pane.add(left_frame, weight=2)
        
        # 新增模特区域
        add_frame = ttk.LabelFrame(left_frame, text="新增模特")
        add_frame.pack(fill=tk.X, pady=5)
        
        add_input_frame = ttk.Frame(add_frame)
        add_input_frame.pack(fill=tk.X, padx=5, pady=5)
        
        add_entry = ttk.Entry(add_input_frame, font=("Arial", 10))
        add_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        add_entry.bind('<Return>', lambda e: add_model())
        
        def add_model():
            raw = add_entry.get().strip()
            if not raw:
                messagebox.showwarning("警告", "请输入模特名称")
                return
            names = [n.strip() for n in re.split(r"[\,\;\n\r\t\s]+", raw) if n.strip()]
            last_id = None
            try:
                for n in names:
                    last_id = self.db.add_model(n)
                add_entry.delete(0, tk.END)
                refresh_list()
                if last_id:
                    models = self.db.get_all_models()
                    for i, model in enumerate(models):
                        if model['id'] == last_id:
                            model_listbox.selection_clear(0, tk.END)
                            model_listbox.selection_set(i)
                            model_listbox.see(i)
                            on_model_select()
                            break
            except ValueError as e:
                messagebox.showwarning("警告", str(e))
        
        ttk.Button(add_input_frame, text="添加", command=add_model).pack(side=tk.LEFT, padx=5)
        
        # 搜索框
        search_frame = ttk.LabelFrame(left_frame, text="搜索")
        search_frame.pack(fill=tk.X, pady=5)
        
        search_entry = ttk.Entry(search_frame, font=("Arial", 10))
        search_entry.pack(fill=tk.X, padx=5, pady=5)
        active_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_frame, text="仅显示有效", variable=active_only_var, command=lambda: filter_list()).pack(anchor=tk.W, padx=5)
        search_entry.bind('<KeyRelease>', lambda e: filter_list())
        
        def filter_list():
            search_text = search_entry.get().lower()
            model_listbox.delete(0, tk.END)
            displayed_models.clear()
            all_models = self.db.get_active_models() if active_only_var.get() else self.db.get_all_models()
            for model in all_models:
                display_text = model['name'] + ("（无效）" if not bool(model.get('is_active', 1)) and not active_only_var.get() else "")
                if not search_text or search_text in display_text.lower():
                    model_listbox.insert(tk.END, display_text)
                    displayed_models.append(model)
        
        # 模特列表
        list_frame = ttk.LabelFrame(left_frame, text="模特列表")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        list_container = ttk.Frame(list_frame)
        list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(list_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        model_listbox = tk.Listbox(list_container, yscrollcommand=scrollbar.set, font=("Arial", 11), exportselection=False)
        model_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 保存左侧列表的选择状态（需要在绑定之前定义）
        saved_model_selection = []
        # 存储当前显示的模型列表（用于通过索引获取ID）
        displayed_models = []
        
        def on_model_listbox_select(event):
            # 更新保存的选择状态
            selection = model_listbox.curselection()
            if selection:
                saved_model_selection[:] = list(selection)
            on_model_select()
        
        model_listbox.bind('<<ListboxSelect>>', on_model_listbox_select)
        scrollbar.config(command=model_listbox.yview)
        
        # 填充列表
        def refresh_list():
            filter_list()
        
        refresh_list()
        
        # 操作按钮
        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, pady=5)
        
        def get_selected_model_id():
            """通过索引获取选中模特的ID（兼容失焦）"""
            selection = saved_model_selection if saved_model_selection else model_listbox.curselection()
            if not selection or not displayed_models:
                return None
            idx = selection[0]
            if 0 <= idx < len(displayed_models):
                return displayed_models[idx]['id']
            return None
        
        def edit_model():
            selection = model_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            model_id = get_selected_model_id()
            if not model_id:
                return
            model = self.db.get_model(model_id)
            if not model:
                return
            
            new_name = simpledialog.askstring("编辑模特", f"请输入新名称 (当前: {model['name']}):")
            if new_name and new_name.strip():
                try:
                    self.db.update_model(model_id, new_name.strip())
                    refresh_list()
                    on_model_select()
                    messagebox.showinfo("成功", f"已更新模特: {new_name}")
                except ValueError as e:
                    messagebox.showwarning("警告", str(e))
        
        def delete_model():
            selection = model_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            model_id = get_selected_model_id()
            if not model_id:
                return
            model = self.db.get_model(model_id)
            if not model:
                return
            
            if messagebox.askyesno("确认", f"确定要删除模特 '{model['name']}' 吗？"):
                self.db.delete_model(model_id)
                refresh_list()
                tag_listbox.delete(0, tk.END)
                tag_info_label.config(text="未选择模特")
                preview_canvas.delete("all")
                preview_label.config(text="未选择模特")
                messagebox.showinfo("成功", f"已删除模特: {model['name']}")
                # 更新当前图片信息
                if self.current_file_id:
                    self.update_image_info()
        
        def move_model_up():
            """向上移动模特"""
            selection = model_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            idx = selection[0]
            if idx == 0:
                messagebox.showinfo("提示", "已经是第一个")
                return
            if idx >= len(displayed_models):
                return
            model_id1 = displayed_models[idx]['id']
            model_id2 = displayed_models[idx - 1]['id']
            self.db.swap_model_order(model_id1, model_id2)
            refresh_list()
            # 恢复选择
            model_listbox.selection_set(idx - 1)
            on_model_select()
        
        def move_model_down():
            """向下移动模特"""
            selection = model_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            idx = selection[0]
            if idx >= len(displayed_models) - 1:
                messagebox.showinfo("提示", "已经是最后一个")
                return
            model_id1 = displayed_models[idx]['id']
            model_id2 = displayed_models[idx + 1]['id']
            self.db.swap_model_order(model_id1, model_id2)
            refresh_list()
            # 恢复选择
            model_listbox.selection_set(idx + 1)
            on_model_select()
        
        ttk.Button(button_frame, text="上移", command=move_model_up).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="下移", command=move_model_down).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="编辑", command=edit_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="删除", command=delete_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="刷新", command=lambda: (refresh_list(), on_model_select())).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="关闭", command=manager_window.destroy).pack(side=tk.RIGHT, padx=5)
        
        # 中间：预览图和详细信息
        middle_frame = ttk.Frame(model_pane)
        model_pane.add(middle_frame, weight=1)
        middle_frame.config(width=250)
        
        # 预览图区域
        preview_frame = ttk.LabelFrame(middle_frame, text="预览图")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        preview_canvas = tk.Canvas(preview_frame, bg="white", width=220, height=220)
        preview_canvas.pack(padx=5, pady=5)
        
        preview_label = ttk.Label(preview_frame, text="未选择模特", font=("Arial", 10))
        preview_label.pack(pady=5)
        type_label = ttk.Label(preview_frame, text="类型")
        type_label.pack(anchor=tk.W, padx=5)
        type_frame = ttk.Frame(preview_frame)
        type_frame.pack(fill=tk.X, padx=5, pady=5)
        model_type_id_var = tk.StringVar()
        type_combo = ttk.Combobox(type_frame, textvariable=model_type_id_var, state="readonly")
        type_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        def reload_model_types():
            try:
                rows = self.db.get_all_model_types()
            except Exception:
                rows = []
            type_combo._items = rows  # 附带原始数据
            type_combo._map = { r.get('name'): r.get('id') for r in rows }
            type_combo['values'] = [r.get('name') for r in rows]
        def add_new_type():
            name = simpledialog.askstring("新增类型", "请输入类型名称：")
            if not name:
                return
            try:
                self.db.add_model_type(name.strip())
                reload_model_types()
            except Exception as e:
                messagebox.showerror("错误", f"新增类型失败: {str(e)}")
        ttk.Button(type_frame, text="新增类型", command=add_new_type).pack(side=tk.RIGHT, padx=6)
        reload_model_types()
        desc_label = ttk.Label(preview_frame, text="简介")
        desc_label.pack(anchor=tk.W, padx=5)
        model_desc_text = tk.Text(preview_frame, height=5, wrap="word")
        model_desc_text.pack(fill=tk.X, padx=5, pady=5)
        
        # 预览图操作按钮
        preview_button_frame = ttk.Frame(preview_frame)
        preview_button_frame.pack(fill=tk.X, padx=5, pady=5)
        
        def set_preview_image():
            selection = model_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            model_id = get_selected_model_id()
            if not model_id:
                return
            
            # 选择图片文件
            file_path = filedialog.askopenfilename(
                title="选择预览图",
                filetypes=[("图片文件", "*.jpg *.jpeg *.png *.gif *.bmp"), ("所有文件", "*.*")]
            )
            if file_path:
                try:
                    self.db.update_model_preview(model_id, file_path)
                    on_model_select()
                    messagebox.showinfo("成功", "预览图已更新")
                except Exception as e:
                    messagebox.showerror("错误", f"更新预览图失败: {str(e)}")
        
        def remove_preview_image():
            selection = model_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            model_id = get_selected_model_id()
            if not model_id:
                return
            
            if messagebox.askyesno("确认", "确定要删除预览图吗？"):
                try:
                    self.db.update_model_preview(model_id, None)
                    on_model_select()
                    messagebox.showinfo("成功", "预览图已删除")
                except Exception as e:
                    messagebox.showerror("错误", f"删除预览图失败: {str(e)}")
        
        ttk.Button(preview_button_frame, text="设置预览图", command=set_preview_image).pack(fill=tk.X, pady=2)
        ttk.Button(preview_button_frame, text="删除预览图", command=remove_preview_image).pack(fill=tk.X, pady=2)
        
        

        # 有效性切换按钮
        model_active_state = {'active': True}
        def update_model_active_btn():
            model_active_btn.config(text=("设为无效" if model_active_state['active'] else "设为有效"))
        def on_toggle_model_active():
            mid = get_selected_model_id()
            if not mid:
                return
            try:
                self.db.update_model_active(mid, not model_active_state['active'])
                model_active_state['active'] = not model_active_state['active']
                update_model_active_btn()
                on_model_select()
            except Exception as e:
                messagebox.showerror("错误", f"更新有效性失败: {str(e)}")
        def save_model_desc():
            model_id = get_selected_model_id()
            if not model_id:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            desc = model_desc_text.get("1.0", tk.END).strip()
            try:
                self.db.update_model_description(model_id, desc)
                on_model_select()
                messagebox.showinfo("成功", "简介已保存")
            except Exception as e:
                messagebox.showerror("错误", f"保存简介失败: {str(e)}")
        ttk.Button(preview_frame, text="保存简介", command=save_model_desc).pack(fill=tk.X, pady=2)
        def save_model_type():
            model_id = get_selected_model_id()
            if not model_id:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            name = model_type_id_var.get().strip()
            type_id = None
            try:
                type_id = getattr(type_combo, '_map', {}).get(name)
            except Exception:
                type_id = None
            if name and not type_id:
                messagebox.showwarning("提示", "请从下拉列表中选择一个有效类型")
                return
            try:
                self.db.update_model_type_id(model_id, type_id)
                on_model_select()
                messagebox.showinfo("成功", "类型已保存")
            except Exception as e:
                messagebox.showerror("错误", f"保存类型失败: {str(e)}")
        ttk.Button(preview_frame, text="保存类型", command=save_model_type).pack(fill=tk.X, pady=2)
        model_active_btn = ttk.Button(preview_frame, text="设为无效", command=on_toggle_model_active)
        model_active_btn.pack(fill=tk.X, pady=2)
        
        # 右侧：标签关联管理
        right_frame = ttk.Frame(model_pane)
        model_pane.add(right_frame, weight=2)
        try:
            right_frame.config(width=360)
            right_frame.pack_propagate(False)
        except Exception:
            pass
        
        tag_info_label = ttk.Label(right_frame, text="未选择模特", font=("Arial", 12, "bold"))
        tag_info_label.pack(pady=5)
        
        # 标签列表显示/隐藏控制
        tag_display_frame = ttk.Frame(right_frame)
        tag_display_frame.pack(fill=tk.X, pady=2)
        tag_display_var = tk.BooleanVar(value=True)
        tag_display_check = ttk.Checkbutton(tag_display_frame, text="显示关联标签", variable=tag_display_var)
        tag_display_check.pack(side=tk.LEFT, padx=5)
        
        # 关联的标签列表
        tag_list_frame = ttk.LabelFrame(right_frame, text="关联的标签")
        tag_list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        def toggle_tag_display():
            if tag_display_var.get():
                tag_list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            else:
                tag_list_frame.pack_forget()
        
        tag_display_var.trace('w', lambda *args: toggle_tag_display())
        
        tag_list_container = ttk.Frame(tag_list_frame)
        tag_list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        tag_scrollbar = ttk.Scrollbar(tag_list_container)
        tag_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        tag_listbox = tk.Listbox(tag_list_container, yscrollcommand=tag_scrollbar.set, font=("Arial", 10), height=20, exportselection=False)
        tag_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tag_scrollbar.config(command=tag_listbox.yview)
        
        # 保存右侧列表的选择状态
        saved_tag_selection = []
        
        # 绑定双击事件以删除标签
        def on_tag_double_click(event):
            # 使用保存的左侧列表选择状态
            if not saved_model_selection:
                # 尝试从当前选择获取
                selection = model_listbox.curselection()
                if not selection:
                    messagebox.showwarning("警告", "请先选择一个模特")
                    return
                saved_model_selection[:] = list(selection)
            else:
                # 恢复保存的选择
                model_listbox.selection_clear(0, tk.END)
                for idx in saved_model_selection:
                    model_listbox.selection_set(idx)
            
            # 使用保存的右侧列表选择状态
            if not saved_tag_selection:
                # 尝试从当前选择获取
                tag_selection = tag_listbox.curselection()
                if not tag_selection:
                    messagebox.showwarning("警告", "请先选择一个标签")
                    return
                saved_tag_selection[:] = list(tag_selection)
            
            model_id = get_selected_model_id()
            if not model_id:
                return
            model = self.db.get_model(model_id)
            
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            tag = self.db.get_tag(tag_id)
            
            # 添加确认对话框
            if messagebox.askyesno("确认", f"确定要从模特 '{model['name']}' 移除标签 '{tag['name']}' 吗？"):
                self.db.remove_model_tag(model_id, tag_id)
                on_model_select()
        
        tag_listbox.bind('<Double-Button-1>', on_tag_double_click)
        
        # 点击时同步选择状态（<<ListboxSelect>>在点击已选中项时不触发）
        def on_tag_listbox_click(event):
            tag_selection = tag_listbox.curselection()
            if tag_selection:
                saved_tag_selection[:] = list(tag_selection)
            tag_listbox.focus_set()
        
        tag_listbox.bind('<Button-1>', on_tag_listbox_click)
        
        # 绑定选择事件以保存右侧列表的选择状态
        def on_tag_listbox_select(event):
            selection = tag_listbox.curselection()
            if selection:
                saved_tag_selection[:] = list(selection)
        
        tag_listbox.bind('<<ListboxSelect>>', on_tag_listbox_select)
        
        # 管理标签关联
        tag_manage_frame = ttk.LabelFrame(right_frame, text="管理标签关联")
        tag_manage_frame.pack(fill=tk.X, pady=5)
        
        def on_model_select():
            # 优先使用保存的选择状态
            if saved_model_selection:
                selection = saved_model_selection
            else:
                selection = model_listbox.curselection()
            
            if not selection:
                tag_listbox.delete(0, tk.END)
                tag_info_label.config(text="未选择模特")
                preview_label.config(text="未选择模特")
                preview_canvas.delete("all")
                saved_model_selection.clear()
                return
            
            # 更新保存的选择状态
            saved_model_selection[:] = list(selection)
            
            model_id = get_selected_model_id()
            if not model_id:
                return
            model = self.db.get_model(model_id)
            if not model:
                return
            
            tag_info_label.config(text=f"模特: {model['name']}")
            preview_label.config(text=model['name'])
            model_desc_text.delete("1.0", tk.END)
            model_desc_text.insert(tk.END, model.get('description') or '')
            # 选择当前类型
            try:
                tid = model.get('model_type_id')
                rows = getattr(type_combo, '_items', [])
                name = ''
                if tid and rows:
                    for r in rows:
                        if r.get('id') == tid:
                            name = r.get('name') or ''
                            break
                if not name:
                    tname = model.get('model_type') or ''
                    # 如果旧文本存在且在列表中，选中；否则清空
                    if getattr(type_combo, '_map', None) and tname in type_combo._map:
                        name = tname
                model_type_id_var.set(name)
            except Exception:
                model_type_id_var.set('')
            try:
                model_active_state['active'] = bool(model.get('is_active', 1))
            except Exception:
                model_active_state['active'] = True
            update_model_active_btn()
            
            # 显示预览图
            preview_canvas.delete("all")
            if model.get('preview_image_path'):
                try:
                    img = self.load_image_from_base64(model['preview_image_path'])
                    if img:
                        img.thumbnail((200, 200), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(img)
                        preview_canvas.create_image(110, 110, image=photo, anchor=tk.CENTER)
                        preview_canvas.image = photo  # 保持引用
                    else:
                        preview_canvas.create_text(110, 110, text="预览图加载失败", fill="red")
                except Exception as e:
                    preview_canvas.create_text(110, 110, text="预览图加载失败", fill="red")
            else:
                preview_canvas.create_text(110, 110, text="无预览图", fill="gray")
            
            # 获取关联的标签
            tags = self.db.get_model_tags(model_id)
            tag_listbox.delete(0, tk.END)
            displayed_tags.clear()
            for tag in tags:
                tag_listbox.insert(tk.END, tag['name'])
                displayed_tags.append(tag)
        
        # 存储当前显示的标签列表（用于通过索引获取ID）
        displayed_tags = []
        
        def get_selected_tag_id():
            """通过索引获取选中标签的ID"""
            tag_selection = tag_listbox.curselection()
            if not tag_selection or not displayed_tags:
                return None
            idx = tag_selection[0]
            if 0 <= idx < len(displayed_tags):
                return displayed_tags[idx]['id']
            return None
        
        def add_tag_to_model():
            # 优先使用保存的选择状态
            if saved_model_selection:
                selection = saved_model_selection
            else:
                selection = model_listbox.curselection()
            
            if not selection:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            
            model_id = get_selected_model_id()
            if not model_id:
                return
            
            # 打开标签选择对话框
            all_tags = self.db.get_tags_with_category_name()
            current_tags = self.db.get_model_tags(model_id)
            current_tag_ids = {t['id'] for t in current_tags}
            
            tag_dialog = tk.Toplevel(manager_window)
            tag_dialog.title("选择标签")
            try:
                sw = tag_dialog.winfo_screenwidth()
                sh = tag_dialog.winfo_screenheight()
            except Exception:
                sw, sh = 1280, 800
            w = max(720, int(sw * 0.6))
            h = max(560, int(sh * 0.7))
            tag_dialog.geometry(f"{w}x{h}")
            tag_dialog.minsize(560, 480)
            tag_dialog.resizable(True, True)
            tag_dialog.transient(manager_window)
            tag_dialog.grab_set()

            # 使用复选框替代Listbox
            tag_frame = ttk.LabelFrame(tag_dialog, text="选择标签（可多选）")
            tag_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            tag_canvas, tag_scrollbar, tag_scrollable_frame = self._create_scrollable_frame(tag_frame)
            tag_canvas.pack(side="left", fill="both", expand=True)
            tag_scrollbar.pack(side="right", fill="y")

            # 顶部搜索框
            search_frame2 = ttk.Frame(tag_dialog)
            search_frame2.pack(fill=tk.X, padx=10, pady=5)
            search_entry2 = ttk.Entry(search_frame2)
            search_entry2.pack(fill=tk.X)

            # 存储复选框变量
            tag_vars = {}
            def render_checks(filter_text: str = ""):
                for child in tag_scrollable_frame.winfo_children():
                    child.destroy()
                tag_vars.clear()
                ft = (filter_text or "").lower()
                groups = {}
                ordered_keys = []
                for t in all_tags:
                    key = t.get('category_id') or 'UNCATEGORIZED'
                    if key not in groups:
                        groups[key] = {'name': t.get('category_name') or '未分类', 'tags': []}
                        ordered_keys.append(key)
                    nm = t.get('name') or ''
                    cn = t.get('category_name') or ''
                    if ft and (ft not in nm.lower()) and (ft not in cn.lower()):
                        continue
                    groups[key]['tags'].append(t)
                max_cols = 6
                for key in ordered_keys:
                    group = groups[key]
                    if not group['tags']:
                        continue
                    section = ttk.LabelFrame(tag_scrollable_frame, text=group['name'])
                    section.pack(fill=tk.X, expand=False, padx=2, pady=2)
                    for c in range(max_cols):
                        section.grid_columnconfigure(c, weight=1)
                    for i, t in enumerate(group['tags']):
                        v = tk.BooleanVar()
                        tag_vars[t['id']] = v
                        if t['id'] in current_tag_ids:
                            v.set(True)
                        label_text = t['name']
                        cb = ttk.Checkbutton(section, text=label_text, variable=v)
                        cb.grid(row=i // max_cols, column=i % max_cols, padx=2, pady=1, sticky="w")
            render_checks()
            search_entry2.bind('<KeyRelease>', lambda e: render_checks(search_entry2.get()))
            
            def save_tag_association():
                # 获取选中的标签
                selected_tag_ids = [tag_id for tag_id, var in tag_vars.items() if var.get()]
                self.db.set_model_tags(model_id, selected_tag_ids)
                on_model_select()
                tag_dialog.destroy()
            
            button_frame2 = ttk.Frame(tag_dialog)
            button_frame2.pack(fill=tk.X, padx=10, pady=10)
            ttk.Button(button_frame2, text="确定", command=save_tag_association).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame2, text="取消", command=tag_dialog.destroy).pack(side=tk.LEFT, padx=5)
        
        def remove_tag_from_model():
            # 优先使用保存的左侧列表选择状态
            if saved_model_selection:
                selection = saved_model_selection
            else:
                selection = model_listbox.curselection()
            
            if not selection:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            
            # 优先使用保存的右侧列表选择状态
            if saved_tag_selection:
                tag_selection = saved_tag_selection
            else:
                tag_selection = tag_listbox.curselection()
            
            if not tag_selection:
                messagebox.showwarning("警告", "请先选择一个标签")
                return
            
            model_id = get_selected_model_id()
            if not model_id:
                return
            model = self.db.get_model(model_id)
            
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            tag = self.db.get_tag(tag_id)
            
            # 添加确认对话框
            if messagebox.askyesno("确认", f"确定要从模特 '{model['name']}' 移除标签 '{tag['name']}' 吗？"):
                self.db.remove_model_tag(model_id, tag_id)
                on_model_select()
        
        ttk.Button(tag_manage_frame, text="添加标签", command=add_tag_to_model).pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(tag_manage_frame, text="移除标签", command=remove_tag_from_model).pack(fill=tk.X, padx=5, pady=5)
    
    def open_tag_manager(self):
        """打开标签管理窗口"""
        # 如果已有对话框打开，聚焦到已打开的对话框
        if self.current_dialog is not None:
            try:
                self.current_dialog.lift()
                self.current_dialog.focus_force()
                return
            except Exception:
                # 如果对话框已被销毁，清除引用
                self.current_dialog = None
        
        manager_window = tk.Toplevel(self.root)
        manager_window.title("标签管理")
        manager_window.geometry("1280x860")
        try:
            manager_window.minsize(1100, 700)
        except Exception:
            pass
        manager_window.transient(self.root)
        manager_window.grab_set()
        
        # 记录当前打开的对话框
        self.current_dialog = manager_window
        
        # 对话框关闭时清除引用并刷新分类UI
        def on_close():
            self.current_dialog = None
            manager_window.destroy()
            # 刷新主界面的分类选择UI（如果当前有图片）
            if self.current_image_path:
                self.refresh_classification_ui()
        
        manager_window.protocol("WM_DELETE_WINDOW", on_close)
        
        # 可调整布局：左右三栏可拖拽
        tag_pane = ttk.PanedWindow(manager_window, orient=tk.HORIZONTAL)
        tag_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧：标签列表和操作
        left_frame = ttk.Frame(tag_pane)
        tag_pane.add(left_frame, weight=2)
        
        # 新增标签区域
        add_frame = ttk.LabelFrame(left_frame, text="新增标签")
        add_frame.pack(fill=tk.X, pady=5)
        
        add_input_frame = ttk.Frame(add_frame)
        add_input_frame.pack(fill=tk.X, padx=5, pady=5)
        
        add_entry = ttk.Entry(add_input_frame, font=("Arial", 10))
        add_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        category_combo_add = ttk.Combobox(add_input_frame, state="readonly", width=16)
        category_combo_add.pack(side=tk.LEFT, padx=5)
        def refresh_add_categories():
            cats = self.db.get_all_tag_categories()
            category_combo_add['values'] = ["无"] + [c['name'] for c in cats]
            if not category_combo_add.get():
                category_combo_add.set("无")
            return cats
        refresh_add_categories()
        add_entry.bind('<Return>', lambda e: add_tag())
        
        def add_tag():
            name = add_entry.get().strip()
            if not name:
                messagebox.showwarning("警告", "请输入标签名称")
                return
            cats = refresh_add_categories()
            sel = category_combo_add.get()
            cid = None
            if sel and sel != "无":
                cur = next((c for c in cats if c['name']==sel), None)
                cid = cur['id'] if cur else None
            try:
                new_id = self.db.add_tag(name, category_id=cid)
                add_entry.delete(0, tk.END)
                refresh_list()
                all_tags = self.db.get_tags_with_category_name()
                for i, tag in enumerate(all_tags):
                    if tag['id'] == new_id:
                        tag_listbox.selection_clear(0, tk.END)
                        tag_listbox.selection_set(i)
                        tag_listbox.see(i)
                        on_tag_select()
                        break
            except ValueError as e:
                messagebox.showwarning("警告", str(e))
        
        ttk.Button(add_input_frame, text="添加", command=add_tag).pack(side=tk.LEFT, padx=5)
        
        # 搜索框
        search_frame = ttk.LabelFrame(left_frame, text="搜索")
        search_frame.pack(fill=tk.X, pady=5)
        
        search_entry = ttk.Entry(search_frame, font=("Arial", 10))
        search_entry.pack(fill=tk.X, padx=5, pady=5)
        category_filter_combo = ttk.Combobox(search_frame, state="readonly")
        category_filter_combo.pack(fill=tk.X, padx=5, pady=5)
        active_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_frame, text="仅显示有效", variable=active_only_var, command=lambda: filter_list()).pack(anchor=tk.W, padx=5)
        def refresh_category_filter():
            cats = self.db.get_all_tag_categories()
            category_filter_combo['values'] = ["全部"] + [c['name'] for c in cats]
            if not category_filter_combo.get():
                category_filter_combo.set("全部")
            return cats
        refresh_category_filter()
        search_entry.bind('<KeyRelease>', lambda e: filter_list())
        category_filter_combo.bind('<<ComboboxSelected>>', lambda e: filter_list())
        
        def filter_list():
            search_text = search_entry.get().lower()
            tag_listbox.delete(0, tk.END)
            displayed_tags.clear()
            only_active = bool(active_only_var.get())
            all_tags = self.db.get_tags_with_category_name(only_active=only_active)
            cats = self.db.get_all_tag_categories()
            sel = category_filter_combo.get()
            cid = None
            if sel and sel != "全部":
                cur = next((c for c in cats if c['name']==sel), None)
                cid = cur['id'] if cur else None
            for tag in all_tags:
                if cid and tag.get('category_id') != cid:
                    continue
                display_text = tag['name'] + (f"({tag['category_name']})" if tag.get('category_name') else "")
                if not search_text or search_text in display_text.lower():
                    tag_listbox.insert(tk.END, display_text)
                    displayed_tags.append(tag)
        
        # 标签列表
        list_frame = ttk.LabelFrame(left_frame, text="标签列表")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        list_container = ttk.Frame(list_frame)
        list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        scrollbar = ttk.Scrollbar(list_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        tag_listbox = tk.Listbox(list_container, yscrollcommand=scrollbar.set, font=("Arial", 11), exportselection=False)
        tag_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 保存左侧列表的选择状态（需要在绑定之前定义）
        saved_tag_selection = []
        # 存储当前显示的标签列表（用于通过索引获取ID）
        displayed_tags = []
        
        def on_tag_listbox_select(event):
            # 更新保存的选择状态
            selection = tag_listbox.curselection()
            if selection:
                saved_tag_selection[:] = list(selection)
            on_tag_select()
        
        tag_listbox.bind('<<ListboxSelect>>', on_tag_listbox_select)
        scrollbar.config(command=tag_listbox.yview)
        
        # 填充列表
        def refresh_list():
            filter_list()
        
        refresh_list()
        
        # 操作按钮
        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, pady=5)
        
        def get_selected_tag_id():
            """通过索引获取选中标签的ID"""
            selection = saved_tag_selection if saved_tag_selection else tag_listbox.curselection()
            if not selection or not displayed_tags:
                return None
            idx = selection[0]
            if 0 <= idx < len(displayed_tags):
                return displayed_tags[idx]['id']
            return None
        
        def edit_tag():
            selection = tag_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个标签")
                return
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            tag = self.db.get_tag(tag_id)
            if not tag:
                return
            
            new_name = simpledialog.askstring("编辑标签", f"请输入新名称 (当前: {tag['name']}):")
            if new_name and new_name.strip():
                try:
                    self.db.update_tag(tag_id, new_name.strip())
                    refresh_list()
                    on_tag_select()
                    messagebox.showinfo("成功", f"已更新标签: {new_name}")
                except ValueError as e:
                    messagebox.showwarning("警告", str(e))
        
        def delete_tag():
            selection = tag_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个标签")
                return
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            tag = self.db.get_tag(tag_id)
            if not tag:
                return
            
            if messagebox.askyesno("确认", f"确定要删除标签 '{tag['name']}' 吗？"):
                self.db.delete_tag(tag_id)
                refresh_list()
                model_listbox.delete(0, tk.END)
                model_info_label.config(text="未选择标签")
                preview_canvas.delete("all")
                preview_label.config(text="未选择标签")
                messagebox.showinfo("成功", f"已删除标签: {tag['name']}")
                # 更新当前图片信息
                if self.current_file_id:
                    self.update_image_info()
        
        def move_tag_up():
            """向上移动标签"""
            selection = tag_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个标签")
                return
            idx = selection[0]
            if idx == 0:
                messagebox.showinfo("提示", "已经是第一个")
                return
            if idx >= len(displayed_tags):
                return
            tag_id1 = displayed_tags[idx]['id']
            tag_id2 = displayed_tags[idx - 1]['id']
            self.db.swap_tag_order(tag_id1, tag_id2)
            refresh_list()
            # 恢复选择
            tag_listbox.selection_set(idx - 1)
            on_tag_select()
        
        def move_tag_down():
            """向下移动标签"""
            selection = tag_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个标签")
                return
            idx = selection[0]
            if idx >= len(displayed_tags) - 1:
                messagebox.showinfo("提示", "已经是最后一个")
                return
            tag_id1 = displayed_tags[idx]['id']
            tag_id2 = displayed_tags[idx + 1]['id']
            self.db.swap_tag_order(tag_id1, tag_id2)
            refresh_list()
            # 恢复选择
            tag_listbox.selection_set(idx + 1)
            on_tag_select()
        
        ttk.Button(button_frame, text="上移", command=move_tag_up).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="下移", command=move_tag_down).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="编辑", command=edit_tag).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="删除", command=delete_tag).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="刷新", command=lambda: (refresh_list(), on_tag_select())).pack(side=tk.LEFT, padx=5)
        def open_tag_category_manager():
            win = tk.Toplevel(manager_window)
            win.title("标签分类管理")
            win.geometry("500x500")
            left = ttk.Frame(win)
            left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
            addf = ttk.LabelFrame(left, text="新增分类")
            addf.pack(fill=tk.X, pady=5)
            addinp = ttk.Frame(addf)
            addinp.pack(fill=tk.X, padx=5, pady=5)
            add_entry2 = ttk.Entry(addinp, font=("Arial", 10))
            add_entry2.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            def add_cat():
                n = add_entry2.get().strip()
                if not n:
                    messagebox.showwarning("警告", "请输入分类名称")
                    return
                try:
                    self.db.add_tag_category(n)
                    add_entry2.delete(0, tk.END)
                    refresh_cat_list()
                except ValueError as e:
                    messagebox.showwarning("警告", str(e))
            ttk.Button(addinp, text="添加", command=add_cat).pack(side=tk.LEFT, padx=5)
            listf = ttk.LabelFrame(left, text="分类列表")
            listf.pack(fill=tk.BOTH, expand=True, pady=5)
            listc = ttk.Frame(listf)
            listc.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            sbar = ttk.Scrollbar(listc)
            sbar.pack(side=tk.RIGHT, fill=tk.Y)
            cat_listbox = tk.Listbox(listc, yscrollcommand=sbar.set, font=("Arial", 11), exportselection=False)
            cat_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sbar.config(command=cat_listbox.yview)
            displayed_categories = []
            def refresh_cat_list():
                cat_listbox.delete(0, tk.END)
                displayed_categories.clear()
                for c in self.db.get_all_tag_categories():
                    cat_listbox.insert(tk.END, c['name'])
                    displayed_categories.append(c)
            refresh_cat_list()
            def get_selected_category_id():
                sel = cat_listbox.curselection()
                if not sel or not displayed_categories:
                    return None
                idx = sel[0]
                if 0 <= idx < len(displayed_categories):
                    return displayed_categories[idx]['id']
                return None
            def move_cat_up():
                sel = cat_listbox.curselection()
                if not sel:
                    messagebox.showwarning("警告", "请先选择一个分类")
                    return
                idx = sel[0]
                if idx <= 0:
                    messagebox.showinfo("提示", "已经是第一个")
                    return
                cur = displayed_categories[idx]
                prev = displayed_categories[idx - 1]
                cur_order = cur.get('sort_order') or 0
                prev_order = prev.get('sort_order') or 0
                self.db.update_tag_category_sort_order(cur['id'], prev_order)
                self.db.update_tag_category_sort_order(prev['id'], cur_order)
                refresh_cat_list()
                cat_listbox.selection_set(idx - 1)
            def move_cat_down():
                sel = cat_listbox.curselection()
                if not sel:
                    messagebox.showwarning("警告", "请先选择一个分类")
                    return
                idx = sel[0]
                if idx >= len(displayed_categories) - 1:
                    messagebox.showinfo("提示", "已经是最后一个")
                    return
                cur = displayed_categories[idx]
                nxt = displayed_categories[idx + 1]
                cur_order = cur.get('sort_order') or 0
                next_order = nxt.get('sort_order') or 0
                self.db.update_tag_category_sort_order(cur['id'], next_order)
                self.db.update_tag_category_sort_order(nxt['id'], cur_order)
                refresh_cat_list()
                cat_listbox.selection_set(idx + 1)
            def edit_cat():
                sel = cat_listbox.curselection()
                if not sel:
                    messagebox.showwarning("警告", "请先选择一个分类")
                    return
                cid = get_selected_category_id()
                if not cid:
                    return
                cur = next((c for c in displayed_categories if c['id']==cid), None)
                if not cur:
                    return
                new_name = simpledialog.askstring("编辑分类", f"请输入新名称 (当前: {cur['name']}):")
                if new_name and new_name.strip():
                    try:
                        self.db.update_tag_category(cid, name=new_name.strip())
                        refresh_cat_list()
                        messagebox.showinfo("成功", f"已更新分类: {new_name}")
                    except Exception as e:
                        messagebox.showwarning("警告", str(e))
            def toggle_cat_active():
                cid = get_selected_category_id()
                if not cid:
                    messagebox.showwarning("警告", "请先选择一个分类")
                    return
                cur = next((c for c in displayed_categories if c['id']==cid), None)
                if not cur:
                    return
                is_active = 0 if cur.get('is_active',1) else 1
                self.db.update_tag_category(cid, is_active=bool(is_active))
                refresh_cat_list()
            def delete_cat():
                cid = get_selected_category_id()
                if not cid:
                    messagebox.showwarning("警告", "请先选择一个分类")
                    return
                if messagebox.askyesno("确认", "确定要删除该分类吗？"):
                    self.db.delete_tag_category(cid)
                    refresh_cat_list()
            bf = ttk.Frame(left)
            bf.pack(fill=tk.X, pady=5)
            ttk.Button(bf, text="上移", command=move_cat_up).pack(side=tk.LEFT, padx=5)
            ttk.Button(bf, text="下移", command=move_cat_down).pack(side=tk.LEFT, padx=5)
            ttk.Button(bf, text="编辑", command=edit_cat).pack(side=tk.LEFT, padx=5)
            ttk.Button(bf, text="切换有效性", command=toggle_cat_active).pack(side=tk.LEFT, padx=5)
            ttk.Button(bf, text="删除", command=delete_cat).pack(side=tk.LEFT, padx=5)
            ttk.Button(bf, text="关闭", command=win.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="分类管理", command=open_tag_category_manager).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="关闭", command=manager_window.destroy).pack(side=tk.RIGHT, padx=5)
        
        # 中间：预览图和详细信息
        middle_frame = ttk.Frame(tag_pane)
        tag_pane.add(middle_frame, weight=1)
        middle_frame.config(width=250)
        
        # 预览图区域
        preview_frame = ttk.LabelFrame(middle_frame, text="预览图")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        preview_canvas = tk.Canvas(preview_frame, bg="white", width=220, height=220)
        preview_canvas.pack(padx=5, pady=5)
        
        preview_label = ttk.Label(preview_frame, text="未选择标签", font=("Arial", 10))
        preview_label.pack(pady=5)
        desc_label2 = ttk.Label(preview_frame, text="简介")
        desc_label2.pack(anchor=tk.W, padx=5)
        tag_desc_text = tk.Text(preview_frame, height=5, wrap="word")
        tag_desc_text.pack(fill=tk.X, padx=5, pady=5)
        cat_frame = ttk.Frame(preview_frame)
        cat_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(cat_frame, text="所属分类").pack(side=tk.LEFT)
        category_combo = ttk.Combobox(cat_frame, state="readonly")
        category_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        def refresh_category_options():
            cats = self.db.get_all_tag_categories()
            names = ["无"] + [c['name'] for c in cats]
            category_combo['values'] = names
            return cats
        current_categories = refresh_category_options()
        def save_tag_category():
            tid = get_selected_tag_id()
            if not tid:
                return
            name = category_combo.get()
            if not name or name == "无":
                self.db.set_tag_category(tid, None)
                try:
                    refresh_list()
                    idx = next((i for i,t in enumerate(displayed_tags) if t.get('id')==tid), None)
                    if idx is not None:
                        tag_listbox.selection_clear(0, tk.END)
                        tag_listbox.selection_set(idx)
                        tag_listbox.see(idx)
                    on_tag_select()
                    messagebox.showinfo("成功", "分类已保存：无")
                except Exception:
                    on_tag_select()
                return
            cats = self.db.get_all_tag_categories()
            found = next((c for c in cats if c['name']==name), None)
            if found:
                self.db.set_tag_category(tid, found['id'])
                try:
                    refresh_list()
                    idx = next((i for i,t in enumerate(displayed_tags) if t.get('id')==tid), None)
                    if idx is not None:
                        tag_listbox.selection_clear(0, tk.END)
                        tag_listbox.selection_set(idx)
                        tag_listbox.see(idx)
                    on_tag_select()
                    messagebox.showinfo("成功", f"分类已保存：{found['name']}")
                except Exception:
                    on_tag_select()
            else:
                messagebox.showwarning("警告", "未找到选中的分类名称，无法保存")
        ttk.Button(preview_frame, text="保存分类", command=save_tag_category).pack(fill=tk.X, pady=2)
        
        # 预览图操作按钮
        preview_button_frame = ttk.Frame(preview_frame)
        preview_button_frame.pack(fill=tk.X, padx=5, pady=5)
        
        def set_preview_image():
            selection = tag_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个标签")
                return
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            
            # 选择图片文件
            file_path = filedialog.askopenfilename(
                title="选择预览图",
                filetypes=[("图片文件", "*.jpg *.jpeg *.png *.gif *.bmp"), ("所有文件", "*.*")]
            )
            if file_path:
                try:
                    self.db.update_tag_preview(tag_id, file_path)
                    on_tag_select()
                    messagebox.showinfo("成功", "预览图已更新")
                except Exception as e:
                    messagebox.showerror("错误", f"更新预览图失败: {str(e)}")
        
        def remove_preview_image():
            selection = tag_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个标签")
                return
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            
            if messagebox.askyesno("确认", "确定要删除预览图吗？"):
                try:
                    self.db.update_tag_preview(tag_id, None)
                    on_tag_select()
                    messagebox.showinfo("成功", "预览图已删除")
                except Exception as e:
                    messagebox.showerror("错误", f"删除预览图失败: {str(e)}")
        
        ttk.Button(preview_button_frame, text="设置预览图", command=set_preview_image).pack(fill=tk.X, pady=2)
        ttk.Button(preview_button_frame, text="删除预览图", command=remove_preview_image).pack(fill=tk.X, pady=2)
        # 标签有效性切换按钮
        tag_active_state = {'active': True}
        def update_tag_active_btn():
            tag_active_btn.config(text=("设为无效" if tag_active_state['active'] else "设为有效"))
        def on_toggle_tag_active():
            tid = get_selected_tag_id()
            if not tid:
                return
            try:
                self.db.update_tag_active(tid, not tag_active_state['active'])
                tag_active_state['active'] = not tag_active_state['active']
                update_tag_active_btn()
                on_tag_select()
            except Exception as e:
                messagebox.showerror("错误", f"更新有效性失败: {str(e)}")
        def save_tag_desc():
            selection = tag_listbox.curselection()
            if not selection:
                messagebox.showwarning("警告", "请先选择一个标签")
                return
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            desc = tag_desc_text.get("1.0", tk.END).strip()
            try:
                self.db.update_tag_description(tag_id, desc)
                on_tag_select()
                messagebox.showinfo("成功", "简介已保存")
            except Exception as e:
                messagebox.showerror("错误", f"保存简介失败: {str(e)}")
        ttk.Button(preview_frame, text="保存简介", command=save_tag_desc).pack(fill=tk.X, pady=2)
        tag_active_btn = ttk.Button(preview_frame, text="设为无效", command=on_toggle_tag_active)
        tag_active_btn.pack(fill=tk.X, pady=2)
        
        # 右侧：模特关联管理
        right_frame = ttk.Frame(tag_pane)
        tag_pane.add(right_frame, weight=2)
        try:
            right_frame.config(width=360)
            right_frame.pack_propagate(False)
        except Exception:
            pass
        
        model_info_label = ttk.Label(right_frame, text="未选择标签", font=("Arial", 12, "bold"))
        model_info_label.pack(pady=5)
        
        # 模特列表显示/隐藏控制
        model_display_frame = ttk.Frame(right_frame)
        model_display_frame.pack(fill=tk.X, pady=2)
        model_display_var = tk.BooleanVar(value=True)
        model_display_check = ttk.Checkbutton(model_display_frame, text="显示关联模特", variable=model_display_var)
        model_display_check.pack(side=tk.LEFT, padx=5)
        
        # 关联的模特列表
        model_list_frame = ttk.LabelFrame(right_frame, text="关联的模特")
        model_list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        def toggle_model_display():
            if model_display_var.get():
                model_list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            else:
                model_list_frame.pack_forget()
        
        model_display_var.trace('w', lambda *args: toggle_model_display())
        
        model_list_container = ttk.Frame(model_list_frame)
        model_list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        model_scrollbar = ttk.Scrollbar(model_list_container)
        model_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        model_listbox = tk.Listbox(model_list_container, yscrollcommand=model_scrollbar.set, font=("Arial", 10), exportselection=False)
        model_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        model_scrollbar.config(command=model_listbox.yview)
        
        # 保存右侧列表的选择状态
        saved_model_selection = []
        
        # 绑定双击事件以删除模特
        def on_model_double_click(event):
            # 使用保存的左侧列表选择状态
            if not saved_tag_selection:
                # 尝试从当前选择获取
                selection = tag_listbox.curselection()
                if not selection:
                    messagebox.showwarning("警告", "请先选择一个标签")
                    return
                saved_tag_selection[:] = list(selection)
            else:
                # 恢复保存的选择
                tag_listbox.selection_clear(0, tk.END)
                for idx in saved_tag_selection:
                    tag_listbox.selection_set(idx)
            
            # 使用保存的右侧列表选择状态
            if not saved_model_selection:
                # 尝试从当前选择获取
                model_selection = model_listbox.curselection()
                if not model_selection:
                    messagebox.showwarning("警告", "请先选择一个模特")
                    return
                saved_model_selection[:] = list(model_selection)
            
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            tag = self.db.get_tag(tag_id)
            
            model_id = get_selected_model_id_from_list()
            if not model_id:
                return
            model = self.db.get_model(model_id)
            
            # 添加确认对话框
            if messagebox.askyesno("确认", f"确定要从标签 '{tag['name']}' 移除模特 '{model['name']}' 吗？"):
                self.db.remove_model_tag(model_id, tag_id)
                on_tag_select()
        
        model_listbox.bind('<Double-Button-1>', on_model_double_click)
        
        # 点击时同步选择状态（<<ListboxSelect>>在点击已选中项时不触发）
        def on_model_listbox_click(event):
            model_selection = model_listbox.curselection()
            if model_selection:
                saved_model_selection[:] = list(model_selection)
            model_listbox.focus_set()
        
        model_listbox.bind('<Button-1>', on_model_listbox_click)
        
        # 绑定选择事件以保存右侧列表的选择状态
        def on_model_listbox_select(event):
            selection = model_listbox.curselection()
            if selection:
                saved_model_selection[:] = list(selection)
        
        model_listbox.bind('<<ListboxSelect>>', on_model_listbox_select)
        
        # 管理模特关联
        model_manage_frame = ttk.LabelFrame(right_frame, text="管理模特关联")
        model_manage_frame.pack(fill=tk.X, pady=5)
        
        # 存储当前显示的模特列表（用于通过索引获取ID）
        displayed_models = []
        
        def get_selected_model_id_from_list():
            """通过索引获取选中模特的ID（从关联模特列表）"""
            model_selection = model_listbox.curselection()
            if not model_selection or not displayed_models:
                return None
            idx = model_selection[0]
            if 0 <= idx < len(displayed_models):
                return displayed_models[idx]['id']
            return None
        
        def on_tag_select():
            # 优先使用保存的选择状态
            if saved_tag_selection:
                selection = saved_tag_selection
            else:
                selection = tag_listbox.curselection()
            
            if not selection:
                model_listbox.delete(0, tk.END)
                displayed_models.clear()
                model_info_label.config(text="未选择标签")
                preview_label.config(text="未选择标签")
                preview_canvas.delete("all")
                saved_tag_selection.clear()
                return
            
            # 更新保存的选择状态
            saved_tag_selection[:] = list(selection)
            
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            tag = self.db.get_tag(tag_id)
            if not tag:
                return
            
            model_info_label.config(text=f"标签: {tag['name']}")
            preview_label.config(text=tag['name'])
            tag_desc_text.delete("1.0", tk.END)
            tag_desc_text.insert(tk.END, tag.get('description') or '')
            try:
                tag_active_state['active'] = bool(tag.get('is_active', 1))
            except Exception:
                tag_active_state['active'] = True
            update_tag_active_btn()
            try:
                cats = refresh_category_options()
                cid = tag.get('category_id')
                if cid:
                    nm = next((c['name'] for c in cats if c['id']==cid), None)
                    category_combo.set(nm or "无")
                else:
                    category_combo.set("无")
            except Exception:
                pass
            
            # 显示预览图
            preview_canvas.delete("all")
            if tag.get('preview_image_path'):
                try:
                    img = self.load_image_from_base64(tag['preview_image_path'])
                    if img:
                        img.thumbnail((200, 200), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(img)
                        preview_canvas.create_image(110, 110, image=photo, anchor=tk.CENTER)
                        preview_canvas.image = photo  # 保持引用
                    else:
                        preview_canvas.create_text(110, 110, text="预览图加载失败", fill="red")
                except Exception as e:
                    preview_canvas.create_text(110, 110, text="预览图加载失败", fill="red")
            else:
                preview_canvas.create_text(110, 110, text="无预览图", fill="gray")
            
            # 获取关联的模特（需要查询model_tags表）
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.* FROM models m
                INNER JOIN model_tags mt ON m.id = mt.model_id
                WHERE mt.tag_id = ?
                ORDER BY m.sort_order, m.name
            ''', (tag_id,))
            models = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            model_listbox.delete(0, tk.END)
            displayed_models.clear()
            for model in models:
                model_listbox.insert(tk.END, model['name'])
                displayed_models.append(model)
        
        def add_model_to_tag():
            # 优先使用保存的选择状态
            if saved_tag_selection:
                selection = saved_tag_selection
            else:
                selection = tag_listbox.curselection()
            
            if not selection:
                messagebox.showwarning("警告", "请先选择一个标签")
                return
            
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            
            # 获取已关联的模特
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.id FROM models m
                INNER JOIN model_tags mt ON m.id = mt.model_id
                WHERE mt.tag_id = ?
            ''', (tag_id,))
            current_model_ids = {row['id'] for row in cursor.fetchall()}
            conn.close()
            
            # 打开模特选择对话框
            all_models = self.db.get_all_models()
            
            model_dialog = tk.Toplevel(manager_window)
            model_dialog.title("选择模特（只能选择已有模特）")
            model_dialog.geometry("350x500")
            model_dialog.transient(manager_window)
            model_dialog.grab_set()
            
            # 使用复选框替代Listbox
            model_frame = ttk.LabelFrame(model_dialog, text="选择模特（可多选）")
            model_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            model_canvas, model_scrollbar, model_scrollable_frame = self._create_scrollable_frame(model_frame)
            model_canvas.configure(height=350)
            model_canvas.pack(side="left", fill="both", expand=True)
            model_scrollbar.pack(side="right", fill="y")

            # 存储复选框变量
            model_vars = {}
            for model in all_models:
                var = tk.BooleanVar()
                model_vars[model['id']] = var
                if model['id'] in current_model_ids:
                    var.set(True)
                
                checkbutton = ttk.Checkbutton(
                    model_scrollable_frame, 
                    text=model['name'], 
                    variable=var
                )
                checkbutton.pack(anchor="w", padx=5, pady=2)
            
            def save_model_association():
                # 获取选中的模特
                selected_model_ids = [model_id for model_id, var in model_vars.items() if var.get()]
                # 为每个选中的模特添加标签关联
                for model_id in selected_model_ids:
                    self.db.add_model_tag(model_id, tag_id)
                on_tag_select()
                model_dialog.destroy()
            
            button_frame2 = ttk.Frame(model_dialog)
            button_frame2.pack(fill=tk.X, padx=10, pady=10)
            ttk.Button(button_frame2, text="确定", command=save_model_association).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame2, text="取消", command=model_dialog.destroy).pack(side=tk.LEFT, padx=5)
        
        def remove_model_from_tag():
            # 优先使用保存的左侧列表选择状态
            if saved_tag_selection:
                selection = saved_tag_selection
            else:
                selection = tag_listbox.curselection()
            
            if not selection:
                messagebox.showwarning("警告", "请先选择一个标签")
                return
            
            # 优先使用保存的右侧列表选择状态
            if saved_model_selection:
                model_selection = saved_model_selection
            else:
                model_selection = model_listbox.curselection()
            
            if not model_selection:
                messagebox.showwarning("警告", "请先选择一个模特")
                return
            
            tag_id = get_selected_tag_id()
            if not tag_id:
                return
            tag = self.db.get_tag(tag_id)
            
            model_id = get_selected_model_id_from_list()
            if not model_id:
                return
            model = self.db.get_model(model_id)
            
            # 添加确认对话框
            if messagebox.askyesno("确认", f"确定要从标签 '{tag['name']}' 移除模特 '{model['name']}' 吗？"):
                self.db.remove_model_tag(model_id, tag_id)
                on_tag_select()
        
        ttk.Button(model_manage_frame, text="添加模特", command=add_model_to_tag).pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(model_manage_frame, text="移除模特", command=remove_model_from_tag).pack(fill=tk.X, padx=5, pady=5)
    
    def open_file_browser(self):
        """打开文件回显窗口"""
        # 如果已有对话框打开，聚焦到已打开的对话框
        if self.current_dialog is not None:
            try:
                self.current_dialog.lift()
                self.current_dialog.focus_force()
                return
            except Exception:
                # 如果对话框已被销毁，清除引用
                self.current_dialog = None
        
        browser_window = tk.Toplevel(self.root)
        browser_window.title("文件回显 - 已处理文件列表")
        browser_window.geometry("1400x800")
        browser_window.transient(self.root)
        
        # 记录当前打开的对话框
        self.current_dialog = browser_window
        
        # 对话框关闭时清除引用
        def on_close():
            self.current_dialog = None
            browser_window.destroy()
        
        browser_window.protocol("WM_DELETE_WINDOW", on_close)
        
        # 顶部工具栏
        toolbar_frame = ttk.Frame(browser_window)
        toolbar_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(toolbar_frame, text="刷新", command=lambda: refresh_file_list()).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar_frame, text="重复文件处理", command=lambda: open_duplicate_dialog()).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar_frame, text="关闭", command=on_close).pack(side=tk.RIGHT, padx=5)
        
        # 搜索框
        search_frame = ttk.Frame(toolbar_frame)
        search_frame.pack(side=tk.LEFT, padx=10)
        ttk.Label(search_frame, text="搜索:").pack(side=tk.LEFT, padx=5)
        search_entry = ttk.Entry(search_frame, width=30)
        search_entry.pack(side=tk.LEFT, padx=5)
        
        # 主内容区域
        main_container = ttk.Frame(browser_window)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 左侧：文件列表
        left_frame = ttk.Frame(main_container)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=5)
        left_frame.config(width=600)
        try:
            left_frame.pack_propagate(False)
        except Exception:
            pass
        
        list_label = ttk.Label(left_frame, text="文件列表", font=("Arial", 12, "bold"))
        list_label.pack(pady=5)
        
        list_container = ttk.Frame(left_frame)
        list_container.pack(fill=tk.BOTH, expand=True)
        
        list_scrollbar = ttk.Scrollbar(list_container)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        file_listbox = tk.Listbox(list_container, yscrollcommand=list_scrollbar.set, font=("Arial", 10), exportselection=False)
        file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scrollbar.config(command=file_listbox.yview)
        
        # 右侧：文件详情
        right_frame = ttk.Frame(main_container)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        
        # 文件预览图
        preview_frame = ttk.LabelFrame(right_frame, text="文件预览")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        preview_canvas = tk.Canvas(preview_frame, bg="white", width=600, height=400)
        preview_canvas.pack(padx=5, pady=5)
        
        # 文件操作按钮区域
        action_frame = ttk.Frame(right_frame)
        action_frame.pack(fill=tk.X, pady=5)
        
        # 加入黑名单按钮
        blacklist_button = tk.Button(
            action_frame,
            text="🚫 加入黑名单",
            command=lambda: add_to_blacklist_from_browser(),
            bg="#F44336",
            fg="white",
            font=("Arial", 10, "bold"),
            relief=tk.RAISED,
            bd=2,
            cursor="hand2"
        )
        blacklist_button.pack(side=tk.LEFT, padx=5, ipadx=10, ipady=5)
        
        # 更改标签按钮
        change_tags_button = tk.Button(
            action_frame,
            text="🏷️ 更改标签",
            command=lambda: change_file_tags(),
            bg="#FF9800",
            fg="white",
            font=("Arial", 10, "bold"),
            relief=tk.RAISED,
            bd=2,
            cursor="hand2"
        )
        change_tags_button.pack(side=tk.LEFT, padx=5, ipadx=10, ipady=5)
        
        rename_button = tk.Button(
            action_frame,
            text="✏️ 更改源文件名",
            command=lambda: change_original_file_name(),
            bg="#3F51B5",
            fg="white",
            font=("Arial", 10, "bold"),
            relief=tk.RAISED,
            bd=2,
            cursor="hand2"
        )
        rename_button.pack(side=tk.LEFT, padx=5, ipadx=10, ipady=5)
        change_thumb_button = tk.Button(
            action_frame,
            text="🖼️ 更改预览图",
            command=lambda: change_file_thumbnail(),
            bg="#3F51B5",
            fg="white",
            font=("Arial", 10, "bold"),
            relief=tk.RAISED,
            bd=2,
            cursor="hand2"
        )
        change_thumb_button.pack(side=tk.LEFT, padx=5, ipadx=10, ipady=5)
        enlarge_button = tk.Button(
            action_frame,
            text="🔍 放大查看",
            command=lambda: open_full_image(),
            bg="#009688",
            fg="white",
            font=("Arial", 10, "bold"),
            relief=tk.RAISED,
            bd=2,
            cursor="hand2"
        )
        enlarge_button.pack(side=tk.LEFT, padx=5, ipadx=10, ipady=5)
        
        # 文件信息
        info_frame = ttk.LabelFrame(right_frame, text="文件信息")
        info_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 创建信息显示区域（使用Text widget以支持多行和滚动）
        # 使用NORMAL状态以便选中文本，但通过事件阻止编辑
        info_text = tk.Text(info_frame, height=20, wrap=tk.WORD, font=("Arial", 10))
        info_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        # 不设置为DISABLED，以便用户可以选中文本进行复制
        
        # 存储当前选择的文件索引，用于在失去焦点后恢复选择
        current_selected_index = [None]
        
        def save_selection():
            """保存当前列表选择状态"""
            selection = file_listbox.curselection()
            if selection:
                current_selected_index[0] = selection[0]
        
        def restore_selection():
            """恢复列表选择状态"""
            if current_selected_index[0] is not None:
                file_listbox.selection_set(current_selected_index[0])
                file_listbox.see(current_selected_index[0])
        
        def prevent_edit(event):
            """阻止编辑信息框内容（只读）"""
            return "break"
        
        def on_info_text_focus_in(event):
            """信息框获得焦点时，保存列表选择状态"""
            save_selection()
        
        def on_info_text_focus_out(event):
            """信息框失去焦点时，恢复列表焦点和选择状态"""
            restore_selection()
            if current_selected_index[0] is not None:
                file_listbox.focus_set()
        
        # 阻止编辑：绑定所有可能修改内容的事件
        info_text.bind("<Key>", prevent_edit)
        info_text.bind("<Button-2>", prevent_edit)  # 中键粘贴
        info_text.bind("<Button-3>", prevent_edit)  # 右键菜单
        info_text.bind("<Control-v>", prevent_edit)  # Ctrl+V
        info_text.bind("<Control-V>", prevent_edit)
        
        # 绑定焦点事件：允许信息框获得焦点以便复制，但保持列表选择状态
        info_text.bind("<FocusIn>", on_info_text_focus_in)
        info_text.bind("<FocusOut>", on_info_text_focus_out)
        
        # 存储文件数据
        displayed_files = []
        
        def _resolve_path_for_browser(p):
            if not p:
                return p
            s = str(p)
            if os.path.exists(s):
                return s
            try:
                proj_data = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data'))
                data_root = get_data_root()
                s_norm = os.path.normcase(os.path.normpath(s))
                proj_norm = os.path.normcase(proj_data)
                if s_norm.startswith(proj_norm + os.sep) or s_norm == proj_norm:
                    try:
                        rel = os.path.relpath(s_norm, proj_norm)
                        cand = os.path.join(data_root, rel)
                        if os.path.exists(cand):
                            return cand
                    except Exception:
                        pass
                s_slash = s.replace("\\", "/")
                if s_slash.lower().startswith("data/"):
                    try:
                        rel = s_slash[5:]
                        cand = os.path.join(data_root, rel)
                        if os.path.exists(cand):
                            return cand
                    except Exception:
                        pass
            except Exception:
                pass
            return s
        
        def _normalize_record_for_browser(file):
            try:
                p = file.get('file_path')
                tp = file.get('thumbnail_path')
                np = _resolve_path_for_browser(p) if p else p
                ntp = _resolve_path_for_browser(tp) if tp else tp
                if np and np != p:
                    file['file_path'] = np
                    try:
                        fid = file.get('id')
                        if fid and os.path.exists(np):
                            self.db.update_file(fid, file_path=np, file_size=os.path.getsize(np))
                    except Exception:
                        pass
                if ntp and ntp != tp:
                    file['thumbnail_path'] = ntp
                    try:
                        fid = file.get('id')
                        if fid and os.path.exists(ntp):
                            self.db.update_file_thumbnail(fid, ntp)
                    except Exception:
                        pass
            except Exception:
                pass
            return file
        
        def format_file_size(size_bytes):
            """格式化文件大小"""
            if size_bytes is None:
                return "未知"
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size_bytes < 1024.0:
                    return f"{size_bytes:.2f} {unit}"
                size_bytes /= 1024.0
            return f"{size_bytes:.2f} TB"
        
        page_state = {'offset': 0, 'limit': 200, 'loading': False}

        def append_files(files):
            for file in files:
                file = _normalize_record_for_browser(file)
                file_path = file.get('file_path')
                file_name = file.get('original_file_name') or file.get('file_name') or os.path.basename(file_path or '')
                file_id = file['id']
                models = []
                try:
                    models = self.db.get_file_models(file_id)
                except Exception:
                    models = []
                if models:
                    model_names = [m['name'] for m in models]
                    display_text = f"{', '.join(model_names)}-{file_name}"
                else:
                    display_text = file_name
                file_listbox.insert(tk.END, display_text)
                displayed_files.append(file)

        def refresh_file_list():
            """刷新文件列表（分页加载）"""
            file_listbox.delete(0, tk.END)
            displayed_files.clear()
            page_state['offset'] = 0
            page_state['loading'] = True
            search_text = search_entry.get().strip()
            try:
                files = self.db.get_files_page(offset=page_state['offset'], limit=page_state['limit'], search_text=search_text)
            except Exception:
                files = []
            append_files(files)
            page_state['offset'] += len(files)
            page_state['loading'] = False

        def _get_duplicate_latest_files():
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT md5, COUNT(*) as c, MIN(created_at) as earliest
                FROM files
                WHERE md5 IS NOT NULL AND md5 != ''
                GROUP BY md5
                HAVING c > 1
            """)
            groups = [dict(r) for r in cursor.fetchall()]
            duplicates = []
            for g in groups:
                md5 = g.get('md5')
                if not md5:
                    continue
                cursor.execute("""
                    SELECT * FROM files WHERE md5 = ? ORDER BY created_at ASC
                """, (md5,))
                rows = [dict(r) for r in cursor.fetchall()]
                if not rows:
                    continue
                keep = rows[0]
                keep_id = keep.get('id')
                keep_name = keep.get('original_file_name') or keep.get('file_name') or os.path.basename(keep.get('file_path') or '')
                keep_time = keep.get('created_at') or ''
                for r in rows[1:]:
                    r['_dup_keep_id'] = keep_id
                    r['_dup_keep_name'] = keep_name
                    r['_dup_keep_time'] = keep_time
                    duplicates.append(r)
            conn.close()
            duplicates.sort(key=lambda x: x.get('created_at') or '', reverse=True)
            return duplicates

        def _dup_display_text(file):
            name = file.get('original_file_name') or file.get('file_name') or os.path.basename(file.get('file_path') or '')
            keep_name = file.get('_dup_keep_name') or ''
            ct = file.get('created_at') or ''
            keep_time = file.get('_dup_keep_time') or ''
            try:
                models = self.db.get_file_models(file.get('id'))
            except Exception:
                models = []
            mnames = ", ".join([m.get('name') for m in models if m.get('name')]) if models else ""
            parts = [ct, name]
            if mnames:
                parts.insert(1, mnames)
            if keep_name:
                parts.append(f"保留：{keep_name} {keep_time}")
            return " | ".join([p for p in parts if p])

        def _remove_file_record_only(file):
            try:
                self.db.delete_file(file.get('id'))
                return True
            except Exception:
                return False

        def _move_to_bad_and_delete(file):
            file = _normalize_record_for_browser(file)
            file_path = file.get('file_path')
            file_id = file.get('id')
            bad_folder = os.path.join(get_data_root(), "bad")
            os.makedirs(bad_folder, exist_ok=True)
            thumb_path = file.get('thumbnail_path')
            if file_path and os.path.exists(file_path):
                original_filename = file.get('original_file_name') or file.get('file_name') or os.path.basename(file_path)
                target_path = os.path.join(bad_folder, original_filename)
                if os.path.exists(target_path):
                    name, ext = os.path.splitext(original_filename)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    target_path = os.path.join(bad_folder, f"{name}_{timestamp}{ext}")
                shutil.move(file_path, target_path)
            try:
                if thumb_path and os.path.exists(thumb_path):
                    thumb_name = os.path.basename(thumb_path)
                    thumb_target = os.path.join(bad_folder, thumb_name)
                    if os.path.exists(thumb_target):
                        tname, text = os.path.splitext(thumb_name)
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        thumb_target = os.path.join(bad_folder, f"{tname}_{ts}{text}")
                    shutil.move(thumb_path, thumb_target)
            except Exception:
                pass
            try:
                if file_id:
                    self.db.delete_file(file_id)
            except Exception:
                return False
            return True

        def open_duplicate_dialog():
            duplicates = _get_duplicate_latest_files()
            if not duplicates:
                messagebox.showinfo("提示", "未找到重复文件")
                return
            dlg = tk.Toplevel(browser_window)
            dlg.title("重复文件处理")
            dlg.geometry("900x700")
            dlg.transient(browser_window)
            dlg.grab_set()
            top = ttk.Frame(dlg)
            top.pack(fill=tk.X, padx=10, pady=8)
            ttk.Label(top, text=f"重复文件 {len(duplicates)} 条（已保留每组最早记录）").pack(side=tk.LEFT)
            list_frame = ttk.Frame(dlg)
            list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
            canvas, scrollbar, inner = self._create_scrollable_frame(list_frame)
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            dup_vars = {}
            for f in duplicates:
                var = tk.IntVar(value=1)
                dup_vars[f.get('id')] = var
                cb = ttk.Checkbutton(inner, text=_dup_display_text(f), variable=var)
                cb.pack(anchor=tk.W, padx=6, pady=2)
            btns = ttk.Frame(dlg)
            btns.pack(fill=tk.X, padx=10, pady=8)
            def _select_all(v):
                for var in dup_vars.values():
                    var.set(v)
            ttk.Button(btns, text="全选", command=lambda: _select_all(1)).pack(side=tk.LEFT, padx=5)
            ttk.Button(btns, text="全不选", command=lambda: _select_all(0)).pack(side=tk.LEFT, padx=5)
            def _collect_selected():
                ids = {fid for fid, var in dup_vars.items() if var.get() == 1}
                return [f for f in duplicates if f.get('id') in ids]
            def _process_remove_only():
                selected = _collect_selected()
                if not selected:
                    messagebox.showwarning("提示", "请先选择要处理的文件")
                    return
                ok = 0
                for f in selected:
                    if _remove_file_record_only(f):
                        ok += 1
                messagebox.showinfo("完成", f"已删除记录 {ok} 条")
                dlg.destroy()
                refresh_file_list()
            def _process_blacklist():
                selected = _collect_selected()
                if not selected:
                    messagebox.showwarning("提示", "请先选择要处理的文件")
                    return
                if not messagebox.askyesno("确认", f"确定将选中 {len(selected)} 条加入黑名单并删除记录吗？"):
                    return
                ok = 0
                for f in selected:
                    if _move_to_bad_and_delete(f):
                        ok += 1
                messagebox.showinfo("完成", f"已处理 {ok} 条")
                dlg.destroy()
                refresh_file_list()
            ttk.Button(btns, text="仅删除记录", command=_process_remove_only).pack(side=tk.RIGHT, padx=5)
            ttk.Button(btns, text="加入黑名单并删除", command=_process_blacklist).pack(side=tk.RIGHT, padx=5)

        def load_more_if_needed(event=None):
            if page_state['loading']:
                return
            # 当滚动到底部附近时加载更多
            size = file_listbox.size()
            if size == 0:
                return
            # 可见最后一个索引
            try:
                last_visible = file_listbox.nearest(file_listbox.winfo_height())
            except Exception:
                last_visible = size - 1
            if last_visible >= size - 1:
                page_state['loading'] = True
                search_text = search_entry.get().strip()
                try:
                    more = self.db.get_files_page(offset=page_state['offset'], limit=page_state['limit'], search_text=search_text)
                except Exception:
                    more = []
                append_files(more)
                page_state['offset'] += len(more)
                page_state['loading'] = False

        # 悬浮预览（小图）
        preview_tip = {'win': None, 'img': None}

        def hide_preview_tip():
            if preview_tip['win'] is not None:
                try:
                    preview_tip['win'].destroy()
                except Exception:
                    pass
                preview_tip['win'] = None
                preview_tip['img'] = None

        def show_preview_tip_for_index(idx, x_root, y_root):
            hide_preview_tip()
            if idx < 0 or idx >= len(displayed_files):
                return
            file = _normalize_record_for_browser(displayed_files[idx])
            path = file.get('thumbnail_path') or file.get('file_path')
            if not path or not os.path.exists(path):
                return
            try:
                img = self.get_preview_image(path)
                img.thumbnail((220, 160), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                tip = tk.Toplevel(browser_window)
                tip.overrideredirect(True)
                tip.attributes('-topmost', True)
                lbl = tk.Label(tip, image=photo, bd=1, relief=tk.SOLID)
                lbl.pack()
                tip.geometry(f"+{x_root+16}+{y_root+16}")
                preview_tip['win'] = tip
                preview_tip['img'] = photo
            except Exception:
                pass

        def on_list_motion(event):
            try:
                idx = file_listbox.nearest(event.y)
                show_preview_tip_for_index(idx, event.x_root, event.y_root)
            except Exception:
                pass

        def on_list_leave(event):
            hide_preview_tip()
        
        def on_file_select(event=None):
            """当选择文件时更新详情显示"""
            selection = file_listbox.curselection()
            # 保存当前选择状态
            if selection:
                current_selected_index[0] = selection[0]
            if not selection or not displayed_files:
                preview_canvas.delete("all")
                info_text.config(state=tk.NORMAL)
                info_text.delete(1.0, tk.END)
                info_text.config(state=tk.NORMAL)  # 保持NORMAL状态以便选中文本
                return
            
            idx = selection[0]
            if idx >= len(displayed_files):
                return
            
            file = _normalize_record_for_browser(displayed_files[idx])
            file_path = file['file_path']
            file_id = file['id']
            
            # 显示预览图
            preview_canvas.delete("all")
            if os.path.exists(file_path):
                try:
                    img = self.get_preview_image(file_path)
                    # 更新画布以确保获取正确的大小
                    preview_canvas.update_idletasks()
                    # 计算缩放比例以适应画布
                    canvas_width = preview_canvas.winfo_width() or 600
                    canvas_height = preview_canvas.winfo_height() or 400
                    
                    # 留出一些边距
                    max_width = canvas_width - 20
                    max_height = canvas_height - 20
                    
                    img_width, img_height = img.size
                    scale = min(max_width / img_width, max_height / img_height, 1.0)
                    new_width = int(img_width * scale)
                    new_height = int(img_height * scale)
                    
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    preview_canvas.create_image(canvas_width // 2, canvas_height // 2, image=photo, anchor=tk.CENTER)
                    preview_canvas.image = photo  # 保持引用
                except Exception as e:
                    preview_canvas.update_idletasks()
                    canvas_width = preview_canvas.winfo_width() or 600
                    canvas_height = preview_canvas.winfo_height() or 400
                    preview_canvas.create_text(canvas_width // 2, canvas_height // 2, 
                                             text=f"预览图加载失败\n{str(e)}", fill="red", font=("Arial", 12))
            else:
                preview_canvas.update_idletasks()
                canvas_width = preview_canvas.winfo_width() or 600
                canvas_height = preview_canvas.winfo_height() or 400
                preview_canvas.create_text(canvas_width // 2, canvas_height // 2, 
                                         text="文件不存在", fill="gray", font=("Arial", 12))
            
            # 显示文件信息
            info_text.config(state=tk.NORMAL)
            info_text.delete(1.0, tk.END)
            
            info_lines = []
            info_lines.append(f"文件名: {file['file_name']}")
            info_lines.append(f"原文件名: {file.get('original_file_name') or '无'}")
            info_lines.append(f"文件路径: {file_path}")
            info_lines.append(f"文件大小: {format_file_size(file.get('file_size'))}")
            if file.get('file_type'):
                info_lines.append(f"文件类型: {file.get('file_type')}")
            info_lines.append(f"创建时间: {file.get('created_at', '未知')}")
            info_lines.append(f"更新时间: {file.get('updated_at', '未知')}")
            info_lines.append("")
            
            # 获取并显示模特信息
            models = self.db.get_file_models(file_id)
            if models:
                model_names = [m['name'] for m in models]
                info_lines.append(f"所属模特: {', '.join(model_names)}")
            else:
                info_lines.append("所属模特: 无")
            
            file_tags = self.db.get_file_tags(file_id)
            model_tags = []
            for m in models:
                try:
                    model_tags.extend(self.db.get_model_tags(m['id']))
                except Exception:
                    pass
            seen = set()
            merged_names = []
            for t in (file_tags + model_tags):
                tid = t.get('id')
                if tid is not None and tid in seen:
                    continue
                seen.add(tid)
                merged_names.append(t.get('name') or '')
            if merged_names:
                info_lines.append(f"所属标签: {', '.join(merged_names)}")
            else:
                info_lines.append("所属标签: 无")
            
            info_text.insert(1.0, "\n".join(info_lines))
            info_text.config(state=tk.NORMAL)  # 保持NORMAL状态以便选中文本
        
        def change_original_file_name():
            selection = file_listbox.curselection()
            if not selection or not displayed_files:
                messagebox.showwarning("警告", "请先选择一个文件")
                return
            idx = selection[0]
            if idx >= len(displayed_files):
                return
            file = displayed_files[idx]
            file_id = file['id']
            current_name = file.get('original_file_name') or file.get('file_name') or ''
            new_name = simpledialog.askstring("更改源文件名", "请输入新的源文件名：", initialvalue=current_name, parent=browser_window)
            if new_name is None:
                return
            new_name = new_name.strip()
            if not new_name:
                messagebox.showwarning("警告", "源文件名不能为空")
                return
            try:
                self.db.update_original_file_name(file_id, new_name)
                file['original_file_name'] = new_name
                try:
                    models = self.db.get_file_models(file_id)
                except Exception:
                    models = []
                if models:
                    model_names = [m['name'] for m in models]
                    display_text = f"{', '.join(model_names)}-{new_name}"
                else:
                    display_text = new_name
                file_listbox.delete(idx)
                file_listbox.insert(idx, display_text)
                file_listbox.selection_set(idx)
                file_listbox.activate(idx)
                file_listbox.see(idx)
                on_file_select()
                messagebox.showinfo("成功", "源文件名已更新")
            except Exception as e:
                messagebox.showerror("错误", f"更新失败:\n{str(e)}")
        
        def add_to_blacklist_from_browser():
            """从文件回显页面将文件加入黑名单"""
            selection = file_listbox.curselection()
            if not selection or not displayed_files:
                messagebox.showwarning("警告", "请先选择一个文件")
                return
            
            idx = selection[0]
            if idx >= len(displayed_files):
                return
            file = _normalize_record_for_browser(displayed_files[idx])
            file_path = file['file_path']
            file_id = file['id']
            
            if not os.path.exists(file_path):
                messagebox.showerror("错误", "文件不存在")
                return
            
            # 确认操作
            result = messagebox.askyesno("确认", f"确定要将此文件加入黑名单吗？\n文件: {file['file_name']}\n\n文件将被移动到data/bad文件夹，并从数据库中删除。")
            if not result:
                return
            
            try:
                # 确保data/bad文件夹存在
                bad_folder = os.path.join(get_data_root(), "bad")
                os.makedirs(bad_folder, exist_ok=True)
                
                # 获取原文件名（优先使用original_file_name，如果没有则使用file_name）
                original_filename = file.get('original_file_name') or file['file_name']
                # 获取缩略图路径（如果有）
                thumb_path = file.get('thumbnail_path')
                
                # 如果文件已经在bad文件夹中，不需要移动
                if os.path.dirname(file_path) == bad_folder:
                    messagebox.showinfo("提示", "文件已在黑名单文件夹中")
                    # 同步将预览图片加入黑名单（如果存在且不在bad文件夹）
                    try:
                        if thumb_path and os.path.exists(thumb_path):
                            thumb_name = os.path.basename(thumb_path)
                            thumb_target = os.path.join(bad_folder, thumb_name)
                            if os.path.exists(thumb_target):
                                tname, text = os.path.splitext(thumb_name)
                                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                                thumb_target = os.path.join(bad_folder, f"{tname}_{ts}{text}")
                            if os.path.dirname(thumb_path) != bad_folder:
                                shutil.move(thumb_path, thumb_target)
                    except Exception:
                        pass
                    # 删除数据库记录
                    try:
                        self.db.delete_file(file_id)
                        messagebox.showinfo("成功", "已从数据库中删除文件记录")
                        refresh_file_list()
                    except Exception as e:
                        messagebox.showerror("错误", f"删除数据库记录失败:\n{str(e)}")
                    return
                
                # 构建目标路径
                target_path = os.path.join(bad_folder, original_filename)
                
                # 如果目标文件已存在，添加时间戳
                if os.path.exists(target_path):
                    name, ext = os.path.splitext(original_filename)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    target_path = os.path.join(bad_folder, f"{name}_{timestamp}{ext}")
                
                # 移动文件到黑名单文件夹
                shutil.move(file_path, target_path)
                # 同步移动预览图片到黑名单（如果存在）
                try:
                    if thumb_path and os.path.exists(thumb_path):
                        thumb_name = os.path.basename(thumb_path)
                        thumb_target = os.path.join(bad_folder, thumb_name)
                        if os.path.exists(thumb_target):
                            tname, text = os.path.splitext(thumb_name)
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            thumb_target = os.path.join(bad_folder, f"{tname}_{ts}{text}")
                        shutil.move(thumb_path, thumb_target)
                except Exception:
                    pass
                
                # 删除数据库记录
                try:
                    self.db.delete_file(file_id)
                except Exception as e:
                    messagebox.showerror("错误", f"删除数据库记录失败:\n{str(e)}")
                    return
                
                messagebox.showinfo("成功", f"文件已加入黑名单！\n文件已移动到: {target_path}")
                
                # 刷新文件列表
                refresh_file_list()
                
                # 如果列表不为空，自动选择第一项
                if file_listbox.size() > 0:
                    file_listbox.selection_set(0)
                    file_listbox.see(0)
                    on_file_select()
                else:
                    # 清空显示
                    preview_canvas.delete("all")
                    info_text.config(state=tk.NORMAL)
                    info_text.delete(1.0, tk.END)
                    info_text.config(state=tk.NORMAL)
                
            except Exception as e:
                messagebox.showerror("错误", f"加入黑名单失败:\n{str(e)}")
        
        def change_file_tags():
            """在文件回显页面更改文件的标签"""
            selection = file_listbox.curselection()
            if not selection or not displayed_files:
                messagebox.showwarning("警告", "请先选择一个文件")
                return
            
            idx = selection[0]
            if idx >= len(displayed_files):
                return
            
            file = displayed_files[idx]
            file_id = file['id']
            
            # 获取所有标签和当前文件的标签
            all_tags = self.db.get_tags_with_category_name()
            current_tags = self.db.get_file_tags(file_id)
            current_tag_ids = {t['id'] for t in current_tags}
            
            # 创建标签选择对话框
            tag_dialog = tk.Toplevel(browser_window)
            tag_dialog.title("更改文件标签")
            tag_dialog.geometry("600x720")
            tag_dialog.transient(browser_window)
            tag_dialog.grab_set()
            
            # 使用复选框显示标签列表
            tag_frame = ttk.LabelFrame(tag_dialog, text="选择标签（可多选）")
            tag_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            tag_canvas, tag_scrollbar, tag_scrollable_frame = self._create_scrollable_frame(tag_frame)
            tag_canvas.configure(height=560)
            tag_canvas.bind("<MouseWheel>", lambda e: tag_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
            tag_scrollable_frame.bind("<MouseWheel>", lambda e: tag_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

            tag_canvas.pack(side="left", fill="both", expand=True)
            tag_scrollbar.pack(side="right", fill="y")
            
            tag_vars = {}
            columns = 6
            groups = {}
            ordered_keys = []
            for tag in all_tags:
                key = tag.get('category_id') or 'UNCATEGORIZED'
                if key not in groups:
                    groups[key] = {
                        'name': tag.get('category_name') or '未分类',
                        'tags': []
                    }
                    ordered_keys.append(key)
                groups[key]['tags'].append(tag)
            for key in ordered_keys:
                group = groups[key]
                section = ttk.LabelFrame(tag_scrollable_frame, text=group['name'])
                section.pack(fill=tk.X, expand=False, padx=2, pady=2)
                for c in range(columns):
                    section.grid_columnconfigure(c, weight=1)
                for i, tag in enumerate(group['tags']):
                    var = tk.BooleanVar()
                    tag_vars[tag['id']] = var
                    if tag['id'] in current_tag_ids:
                        var.set(True)
                    cb = ttk.Checkbutton(section, text=tag['name'], variable=var)
                    cb.grid(row=i // columns, column=i % columns, sticky="w", padx=2, pady=1)
            
            def save_tag_changes():
                """保存标签更改"""
                # 获取选中的标签ID
                selected_tag_ids = [tag_id for tag_id, var in tag_vars.items() if var.get()]
                
                try:
                    # 更新文件的标签关联
                    self.db.set_file_tags(file_id, selected_tag_ids)
                    
                    # 刷新文件信息显示
                    on_file_select()
                    
                    # 关闭对话框
                    tag_dialog.destroy()
                    
                    messagebox.showinfo("成功", "标签已更新！")
                except Exception as e:
                    messagebox.showerror("错误", f"更新标签失败:\n{str(e)}")
            
            # 按钮区域
            button_frame = ttk.Frame(tag_dialog)
            button_frame.pack(fill=tk.X, padx=10, pady=10)
            ttk.Button(button_frame, text="确定", command=save_tag_changes).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="取消", command=tag_dialog.destroy).pack(side=tk.LEFT, padx=5)

        def change_file_thumbnail():
            selection = file_listbox.curselection()
            if not selection or not displayed_files:
                messagebox.showwarning("警告", "请先选择一个文件")
                return
            idx = selection[0]
            if idx >= len(displayed_files):
                return
            file = displayed_files[idx]
            file_id = file['id']
            file_path = file['file_path']
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in self.VIDEO_EXTENSIONS:
                messagebox.showinfo("提示", "当前仅支持为视频文件更改预览图")
                return
            dlg = tk.Toplevel(browser_window)
            dlg.title("更改预览图")
            dlg.geometry("800x600")
            dlg.transient(browser_window)
            dlg.grab_set()
            thumbs_canvas, thumbs_scroll_y, thumbs_inner = self._create_scrollable_frame(dlg)
            thumbs_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10,0))
            thumbs_scroll_y.pack(fill=tk.Y, side=tk.RIGHT, padx=0, pady=(10,0))
            btns = ttk.Frame(dlg)
            btns.pack(fill=tk.X, padx=10, pady=10)
            thumbs_photos = []
            thumbs_images = []
            thumb_widgets = []
            selected_idx = {'i': 0}
            def draw_selection(canvas, w=200, h=130):
                canvas.delete('sel_border')
                canvas.create_rectangle(2, 2, w-2, h-2, outline='red', width=2, tags='sel_border')
            def clear_selection():
                for tw in thumb_widgets:
                    tw['canvas'].delete('sel_border')
            def make_thumbs(path, count=18):
                for w in thumbs_inner.winfo_children():
                    w.destroy()
                thumbs_photos.clear()
                thumbs_images.clear()
                thumb_widgets.clear()
                cap = cv2.VideoCapture(path)
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if total <= 0:
                    cap.release()
                    return
                try:
                    import random
                    margin = max(1, int(total * 0.03))
                    usable = max(1, total - margin * 2)
                    segment = max(1, usable // (count + 1))
                    positions = []
                    for i in range(1, count + 1):
                        base = margin + i * segment
                        jitter = max(1, segment // 3)
                        pos = base + random.randint(-jitter, jitter)
                        pos = max(0, min(total - 1, pos))
                        positions.append(pos)
                except Exception:
                    positions = [max(0, min(total - 1, int((i/(count+1)) * total))) for i in range(1, count+1)]
                canvas_w = 200
                canvas_h = 130
                cols = 4
                for i, pos in enumerate(positions):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        continue
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(rgb)
                    view_img = pil_img.copy()
                    view_img.thumbnail((canvas_w-10, canvas_h-10), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(view_img)
                    f = tk.Frame(thumbs_inner)
                    r = i // cols
                    c = i % cols
                    f.grid(row=r, column=c, padx=8, pady=8, sticky='n')
                    can = tk.Canvas(f, width=canvas_w, height=canvas_h, bg='white', highlightthickness=0)
                    can.pack()
                    can.create_image(canvas_w//2, canvas_h//2, image=photo, anchor=tk.CENTER)
                    can.image = photo
                    def on_click(e=None, ii=i, cc=can):
                        selected_idx['i'] = ii
                        clear_selection()
                        draw_selection(cc, canvas_w, canvas_h)
                    can.bind('<Button-1>', on_click)
                    thumbs_photos.append(photo)
                    thumbs_images.append(pil_img)
                    thumb_widgets.append({'canvas': can})
                cap.release()
                if thumb_widgets:
                    selected_idx['i'] = 0
                    draw_selection(thumb_widgets[0]['canvas'], canvas_w, canvas_h)
                try:
                    thumbs_inner.update_idletasks()
                    thumbs_canvas.configure(scrollregion=thumbs_canvas.bbox('all'))
                except Exception:
                    pass
            def refresh():
                make_thumbs(file_path)
            def save_selected():
                if not thumbs_images:
                    messagebox.showwarning("警告", "请先生成预览图")
                    return
                i = selected_idx['i']
                if i < 0 or i >= len(thumbs_images):
                    i = 0
                full_img = thumbs_images[i]
                out_img = full_img.copy()
                max_w = 1280
                if out_img.width > max_w or out_img.height > max_w:
                    out_img.thumbnail((max_w, max_w), Image.Resampling.LANCZOS)
                target_folder = os.path.dirname(file_path)
                thumb_filename = f"{file_id}_thumb.jpg"
                thumb_path = os.path.join(target_folder, thumb_filename)
                try:
                    out_img.save(thumb_path, format='JPEG', quality=90, optimize=True, progressive=True, subsampling=0)
                except Exception:
                    out_img.save(thumb_path, format='JPEG', quality=90)
                try:
                    self.db.update_file_thumbnail(file_id, thumb_path)
                    on_file_select()
                    messagebox.showinfo("成功", "预览图已更新！")
                    dlg.destroy()
                except Exception as e:
                    messagebox.showerror("错误", f"更新失败:\n{str(e)}")
            ttk.Button(btns, text="刷新预览图", command=refresh).pack(side=tk.LEFT, padx=5)
            ttk.Button(btns, text="保存为封面", command=save_selected).pack(side=tk.LEFT, padx=5)
            ttk.Button(btns, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=5)
            refresh()
        def open_full_image():
            selection = file_listbox.curselection()
            if not selection or not displayed_files:
                messagebox.showwarning("警告", "请先选择一个文件")
                return
            idx = selection[0]
            if idx >= len(displayed_files):
                return
            file = _normalize_record_for_browser(displayed_files[idx])
            file_path = file['file_path']
            if not os.path.exists(file_path):
                messagebox.showerror("错误", "文件不存在")
                return
            try:
                img = self.get_preview_image(file_path)
            except Exception as e:
                messagebox.showerror("错误", f"打开大图失败: {str(e)}")
                return
            win = tk.Toplevel(browser_window)
            win.title(f"查看大图 - {os.path.basename(file_path)}")
            screen_width = win.winfo_screenwidth()
            screen_height = win.winfo_screenheight()
            original_width, original_height = img.size
            max_width = int(screen_width * 0.9)
            max_height = int(screen_height * 0.9)
            if original_width <= max_width and original_height <= max_height:
                display_width = original_width
                display_height = original_height
            else:
                scale = min(max_width / original_width, max_height / original_height)
                display_width = int(original_width * scale)
                display_height = int(original_height * scale)
                img = img.resize((display_width, display_height), Image.Resampling.LANCZOS)
            win.geometry(f"{display_width + 20}x{display_height + 60}")
            x = (screen_width - display_width - 20) // 2
            y = (screen_height - display_height - 60) // 2
            win.geometry(f"{display_width + 20}x{display_height + 60}+{x}+{y}")
            canvas = tk.Canvas(win, width=display_width, height=display_height, bg="white")
            canvas.pack(padx=10, pady=10)
            photo = ImageTk.PhotoImage(img)
            canvas.create_image(display_width // 2, display_height // 2, image=photo, anchor=tk.CENTER)
            canvas.image = photo
            info_text = f"尺寸: {original_width} x {original_height} 像素 | 文件: {os.path.basename(file_path)}"
            info_label = ttk.Label(win, text=info_text, font=("Arial", 9))
            info_label.pack(pady=5)
            close_button = ttk.Button(win, text="关闭 (ESC)", command=win.destroy)
            close_button.pack(pady=5)
            win.bind("<Escape>", lambda e: win.destroy())
            win.focus_set()

        
        file_listbox.bind('<<ListboxSelect>>', on_file_select)
        file_listbox.bind('<Configure>', load_more_if_needed)
        file_listbox.bind('<MouseWheel>', load_more_if_needed)
        file_listbox.bind('<Motion>', on_list_motion)
        file_listbox.bind('<Leave>', on_list_leave)
        search_entry.bind('<KeyRelease>', lambda e: refresh_file_list())
        
        # 初始加载
        refresh_file_list()
        
        # 如果列表不为空，自动选择第一项
        if file_listbox.size() > 0:
            file_listbox.selection_set(0)
            file_listbox.see(0)
            on_file_select()
    
    def open_export_dialog(self):
        """打开导出对话框"""
        # 如果已有对话框打开，聚焦到已打开的对话框
        if self.current_dialog is not None:
            try:
                self.current_dialog.lift()
                self.current_dialog.focus_force()
                return
            except Exception:
                # 如果对话框已被销毁，清除引用
                self.current_dialog = None
        
        export_window = tk.Toplevel(self.root)
        export_window.title("导出文件")
        export_window.geometry("800x500")
        export_window.transient(self.root)
        try:
            export_window.state('zoomed')
        except Exception:
            pass
        
        # 记录当前打开的对话框
        self.current_dialog = export_window
        
        # 对话框关闭时清除引用
        def on_close():
            self.current_dialog = None
            export_window.destroy()
        
        export_window.protocol("WM_DELETE_WINDOW", on_close)
        
        # 主容器
        main_frame = ttk.Frame(export_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 创建左右两个选择区域
        selection_frame = ttk.Frame(main_frame)
        selection_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        auto_refresh_var = tk.IntVar(value=1)
        
        # 模特选择区域（左侧）
        model_container = ttk.LabelFrame(selection_frame, text="选择模特（可多选）")
        model_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        model_canvas, model_scrollbar, model_scrollable_frame = self._create_scrollable_frame(model_container)

        # 加载模特列表
        models = self.db.get_all_models()
        model_vars = {}  # {id: IntVar}
        model_dict = {}  # {name: id}
        for model in models:
            model_id = model['id']
            model_name = model['name']
            model_dict[model_name] = model_id
            var = tk.IntVar()
            model_vars[model_id] = var
            checkbox = ttk.Checkbutton(model_scrollable_frame, text=model_name, variable=var, command=lambda: (auto_refresh_var.get() and reload_files()))
            checkbox.pack(anchor=tk.W, padx=5, pady=2)
        
        # 绑定鼠标滚轮事件到canvas
        def on_mousewheel_model(event):
            if model_canvas.winfo_containing(event.x_root, event.y_root):
                model_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        model_canvas.bind("<MouseWheel>", on_mousewheel_model)
        model_scrollable_frame.bind("<MouseWheel>", on_mousewheel_model)
        
        model_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        model_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 标签选择区域（右侧）
        tag_container = ttk.LabelFrame(selection_frame, text="选择标签（可多选）")
        tag_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        tag_canvas, tag_scrollbar, tag_scrollable_frame = self._create_scrollable_frame(tag_container)

        # 加载标签列表
        tags = self.db.get_tags_with_category_name()
        tag_vars = {}
        tag_dict = {}
        groups = {}
        ordered_keys = []
        for tag in tags:
            key = tag.get('category_id') or 'UNCATEGORIZED'
            if key not in groups:
                groups[key] = {'name': tag.get('category_name') or '未分类', 'tags': []}
                ordered_keys.append(key)
            groups[key]['tags'].append(tag)
        max_cols = 8
        for key in ordered_keys:
            group = groups[key]
            section = ttk.LabelFrame(tag_scrollable_frame, text=group['name'])
            section.pack(fill=tk.X, expand=False, padx=2, pady=2)
            for c in range(max_cols):
                section.grid_columnconfigure(c, weight=1)
            for i, tag in enumerate(group['tags']):
                tag_id = tag['id']
                tag_name = tag['name']
                tag_dict[tag_name] = tag_id
                var = tk.IntVar()
                tag_vars[tag_id] = var
                cb = ttk.Checkbutton(section, text=tag_name, variable=var, command=lambda: (auto_refresh_var.get() and reload_files()))
                cb.grid(row=i // max_cols, column=i % max_cols, padx=2, pady=1, sticky="w")
        
        # 绑定鼠标滚轮事件到canvas
        def on_mousewheel_tag(event):
            if tag_canvas.winfo_containing(event.x_root, event.y_root):
                tag_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        tag_canvas.bind("<MouseWheel>", on_mousewheel_tag)
        tag_scrollable_frame.bind("<MouseWheel>", on_mousewheel_tag)
        
        tag_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tag_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        file_container = ttk.LabelFrame(main_frame, text="文件列表（默认全选）")
        file_container.pack(fill=tk.BOTH, expand=True, pady=5)
        file_controls = ttk.Frame(file_container)
        file_controls.pack(fill=tk.X, padx=5, pady=5)
        model_name_var = tk.StringVar()
        ttk.Label(file_controls, text="模特名").pack(side=tk.LEFT, padx=(0, 4))
        model_name_entry = ttk.Entry(file_controls, textvariable=model_name_var, width=16)
        model_name_entry.pack(side=tk.LEFT, padx=4)
        model_name_entry.bind('<Return>', lambda e: reload_files())
        ttk.Checkbutton(file_controls, text="自动刷新", variable=auto_refresh_var).pack(side=tk.LEFT, padx=6)
        file_vars = {}
        filtered_files_data = []
        file_canvas, file_scrollbar, file_scrollable_frame = self._create_scrollable_frame(file_container)
        def reload_files():
            nonlocal filtered_files_data
            selected_model_ids = [model_id for model_id, var in model_vars.items() if var.get() == 1]
            selected_tag_ids = [tag_id for tag_id, var in tag_vars.items() if var.get() == 1]
            model_name_q = (model_name_var.get() or '').strip().lower()
            all_files = self.db.get_all_files_with_relations()
            filtered = []
            for info in all_files:
                f = info['file']
                ms = info['models']
                ts = info['tags']
                mids = {m['id'] for m in ms}
                tids = {t['id'] for t in ts}
                mm = True
                tm = True
                if selected_model_ids:
                    mm = any(m in mids for m in selected_model_ids)
                if model_name_q:
                    mm = mm and any(model_name_q in (m.get('name') or '').lower() for m in ms)
                if selected_tag_ids:
                    tm = any(t in tids for t in selected_tag_ids)
                if mm and tm:
                    filtered.append(info)
            filtered_files_data = filtered
            for child in file_scrollable_frame.winfo_children():
                try:
                    child.destroy()
                except Exception:
                    pass
            file_vars.clear()
            for info in filtered_files_data:
                f = info['file']
                name = f.get('original_file_name') or f.get('file_name') or os.path.basename(f['file_path'])
                var = tk.IntVar(value=1)
                file_vars[f['id']] = var
                ttk.Checkbutton(file_scrollable_frame, text=name, variable=var).pack(anchor=tk.W, padx=5, pady=2)
        def select_all_files():
            for var in file_vars.values():
                var.set(1)
        def select_none_files():
            for var in file_vars.values():
                var.set(0)
        ttk.Button(file_controls, text="刷新文件列表", command=reload_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_controls, text="全选", command=select_all_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_controls, text="全不选", command=select_none_files).pack(side=tk.LEFT, padx=5)
        def on_mousewheel_file(event):
            if file_canvas.winfo_containing(event.x_root, event.y_root):
                file_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        file_canvas.bind("<MouseWheel>", on_mousewheel_file)
        file_scrollable_frame.bind("<MouseWheel>", on_mousewheel_file)
        file_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        file_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        options_frame = ttk.Frame(main_frame)
        options_frame.pack(fill=tk.X, pady=5)
        compress_var = tk.StringVar(value="folder")
        ttk.Radiobutton(options_frame, text="最快（不压缩，文件夹）", variable=compress_var, value="folder").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(options_frame, text="标准（压缩zip）", variable=compress_var, value="zip").pack(side=tk.LEFT, padx=5)
        deduplicate_var = tk.IntVar(value=1)
        ttk.Checkbutton(options_frame, text="避免重复写入", variable=deduplicate_var).pack(side=tk.LEFT, padx=15)
        ttk.Label(file_scrollable_frame, text="请选择模特/标签后点击“刷新文件列表”加载").pack(anchor=tk.W, padx=5, pady=6)
        
        # 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        def do_export():
            """执行导出"""
            # 获取选中的模特和标签（可以同时选择）
            selected_model_ids = [model_id for model_id, var in model_vars.items() if var.get() == 1]
            selected_tag_ids = [tag_id for tag_id, var in tag_vars.items() if var.get() == 1]
            selected_file_ids = [fid for fid, var in file_vars.items() if var.get() == 1]
            
            if not selected_model_ids and not selected_tag_ids and not selected_file_ids:
                messagebox.showwarning("警告", "请至少选择条件或在文件列表选择文件")
                return
            
            mode = compress_var.get()
            save_path = None
            if mode == "folder":
                base_dir = filedialog.askdirectory(title="选择导出文件夹")
                if not base_dir:
                    return
                ts = datetime.now().strftime("%Y%m%d%H%M%S")
                save_path = os.path.join(base_dir, ts)
                idx = 1
                while os.path.exists(save_path):
                    save_path = os.path.join(base_dir, f"{ts}_{idx}")
                    idx += 1
                os.makedirs(save_path, exist_ok=True)
            else:
                zip_filename = datetime.now().strftime("%Y%m%d%H%M%S") + ".zip"
                save_path = filedialog.asksaveasfilename(
                    title="保存导出文件",
                    defaultextension=".zip",
                    filetypes=[("ZIP文件", "*.zip"), ("所有文件", "*.*")],
                    initialfile=zip_filename
                )
            
            if not save_path:
                return  # 用户取消了保存
            
            # 执行导出
            try:
                self.export_files(
                    selected_model_ids,
                    selected_tag_ids,
                    save_path,
                    file_ids=selected_file_ids if selected_file_ids else None,
                    compression=mode,
                    deduplicate=bool(deduplicate_var.get())
                )
                messagebox.showinfo("成功", f"导出完成！\n文件已保存到：\n{save_path}")
                on_close()
            except Exception as e:
                messagebox.showerror("错误", f"导出失败：\n{str(e)}")
        
        ttk.Button(button_frame, text="导出", command=do_export).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=on_close).pack(side=tk.LEFT, padx=5)
    
    def export_files(self, model_ids, tag_ids, zip_path, file_ids=None, compression="folder", deduplicate=True):
        all_files = self.db.get_all_files_with_relations()
        filtered_files = []
        if file_ids:
            ids = set(file_ids)
            for info in all_files:
                f = info['file']
                if f.get('id') in ids:
                    filtered_files.append(info)
        else:
            for file_info in all_files:
                file = file_info['file']
                file_models = file_info['models']
                file_tags = file_info['tags']
                file_model_ids = {m['id'] for m in file_models}
                file_tag_ids = {t['id'] for t in file_tags}
                model_match = True
                tag_match = True
                if model_ids:
                    model_match = any(model_id in file_model_ids for model_id in model_ids)
                if tag_ids:
                    tag_match = any(tag_id in file_tag_ids for tag_id in tag_ids)
                if model_match and tag_match:
                    filtered_files.append(file_info)
        if not filtered_files:
            raise Exception("没有找到符合条件的文件")
        zipf_ctx = None
        if compression in ("zip", "deflated"):
            zipf_ctx = zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=1)
        elif compression in ("stored", "zip_stored"):
            zipf_ctx = zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED)
        else:
            os.makedirs(zip_path, exist_ok=True)
        def write_file(path, arcname):
            if zipf_ctx:
                zipf_ctx.write(path, arcname)
            else:
                dst = os.path.join(zip_path, arcname)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(path, dst)
        with (zipf_ctx if zipf_ctx else open(os.devnull, 'w')):
            names = set()
            for file_info in filtered_files:
                file = file_info['file']
                file_models = file_info['models']
                file_tags = file_info['tags']
                original_file_name = file.get('original_file_name') or file.get('file_name') or os.path.basename(file['file_path'])
                if model_ids and tag_ids:
                    if deduplicate:
                        m = None
                        t = None
                        for mm in file_models:
                            if mm['id'] in set(model_ids):
                                m = mm
                                break
                        for tt in file_tags:
                            if tt['id'] in set(tag_ids):
                                t = tt
                                break
                        if m and t:
                            model_name = m['name']
                            tag_name = t['name']
                            base, ext = os.path.splitext(original_file_name)
                            arc_dir = os.path.join(model_name, tag_name)
                            arcname = os.path.join(arc_dir, original_file_name)
                            counter = 1
                            while arcname in names:
                                arcname = os.path.join(arc_dir, f"{base}_{counter}{ext}")
                                counter += 1
                            if os.path.exists(file['file_path']):
                                write_file(file['file_path'], arcname)
                                names.add(arcname)
                    else:
                        for model in file_models:
                            if model['id'] in model_ids:
                                model_name = model['name']
                                for tag in file_tags:
                                    if tag['id'] in tag_ids:
                                        tag_name = tag['name']
                                        base, ext = os.path.splitext(original_file_name)
                                        arc_dir = os.path.join(model_name, tag_name)
                                        arcname = os.path.join(arc_dir, original_file_name)
                                        counter = 1
                                        while arcname in names:
                                            arcname = os.path.join(arc_dir, f"{base}_{counter}{ext}")
                                            counter += 1
                                        if os.path.exists(file['file_path']):
                                            write_file(file['file_path'], arcname)
                                            names.add(arcname)
                elif model_ids:
                    written = False
                    for model in file_models:
                        if model['id'] in model_ids and not written:
                            model_name = model['name']
                            base, ext = os.path.splitext(original_file_name)
                            arc_dir = model_name
                            arcname = os.path.join(arc_dir, original_file_name)
                            counter = 1
                            while arcname in names:
                                arcname = os.path.join(arc_dir, f"{base}_{counter}{ext}")
                                counter += 1
                            if os.path.exists(file['file_path']):
                                write_file(file['file_path'], arcname)
                                names.add(arcname)
                                written = True
                elif tag_ids:
                    written = False
                    for tag in file_tags:
                        if tag['id'] in tag_ids and not written:
                            tag_name = tag['name']
                            base, ext = os.path.splitext(original_file_name)
                            arc_dir = tag_name
                            arcname = os.path.join(arc_dir, original_file_name)
                            counter = 1
                            while arcname in names:
                                arcname = os.path.join(arc_dir, f"{base}_{counter}{ext}")
                                counter += 1
                            if os.path.exists(file['file_path']):
                                write_file(file['file_path'], arcname)
                                names.add(arcname)
                                written = True
                else:
                    base, ext = os.path.splitext(original_file_name)
                    arcname = original_file_name
                    counter = 1
                    while arcname in names:
                        arcname = f"{base}_{counter}{ext}"
                        counter += 1
                    if os.path.exists(file['file_path']):
                        write_file(file['file_path'], arcname)
                        names.add(arcname)


def main():
    root = tk.Tk()
    try:
        root.state('zoomed')
    except Exception:
        pass
    try:
        root.lift()
        root.attributes('-topmost', True)
        root.after(400, lambda: root.attributes('-topmost', False))
    except Exception:
        pass
    app = ImageClassifierApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
