import os
import json
import shutil
import subprocess
import threading
from pathlib import Path
from tkinter import (Tk, Frame, Label, Listbox, Button, Entry, Checkbutton,
                     IntVar, StringVar, messagebox, filedialog, END, Scrollbar,
                     VERTICAL, E, W, N, S, BOTH, RIGHT, LEFT, TOP, X, Y, LabelFrame)

VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.m4v', '.webm'}

DEFAULT_CONFIG = {
    "default_select_all": True,
    "default_delete_after_convert": True,
    "enable_prefix_classify": True,
    "default_scan_dir": "",
    "default_target_dir": "",
    "delete_song_folder_after_move": True,
    "path_mappings": {}
}

class MusicManager:
    def __init__(self, master):
        self.master = master
        master.title("视频转 MP3 智能分类工具")
        try:
            master.state('zoomed')
        except:
            try:
                master.attributes('-zoomed', True)
            except:
                master.geometry("950x750")

        self.config_path = Path.cwd() / "config.json"
        self.config = self.load_or_create_config()  # 已含备份逻辑
        scan_dir = self.config.get("default_scan_dir", "")
        if scan_dir and Path(scan_dir).is_dir():
            self.current_dir = Path(scan_dir)
        else:
            self.current_dir = Path.cwd()

        self.prefix_enabled = self.config.get("enable_prefix_classify", True)
        self.default_target = self.config.get("default_target_dir", "")
        self.delete_song_folder = self.config.get("delete_song_folder_after_move", True)
        self.path_mappings = self.config.get("path_mappings", {})

        self.delete_var = IntVar(value=1 if self.config.get("default_delete_after_convert", True) else 0)
        self.prefix_var = IntVar(value=1 if self.prefix_enabled else 0)
        self.target_dir = StringVar(value=self.default_target if self.default_target else "")
        self.status_var = StringVar(value="就绪")

        if not shutil.which('ffmpeg'):
            messagebox.showerror("错误", "未找到 ffmpeg，请先安装并加入系统 PATH。")
            master.destroy()
            return

        self.build_ui()
        self.update_mapping_listbox()
        self.refresh_list()

        if self.config.get("default_select_all", True):
            self.select_all()
        else:
            self.deselect_all()

    # ---------- 配置备份与加载 ----------
    def load_or_create_config(self):
        # 如果文件不存在，直接创建默认并返回
        if not self.config_path.exists():
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            return DEFAULT_CONFIG.copy()

        # 文件存在，尝试加载
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 检查是否缺少必需键
            for key in DEFAULT_CONFIG:
                if key not in config:
                    raise ValueError(f"缺少配置项: {key}")
            return config
        except (json.JSONDecodeError, ValueError, IOError):
            # 格式错误或缺少键 → 备份原文件后重建
            self.backup_config()
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            return DEFAULT_CONFIG.copy()

    def backup_config(self):
        """将现有 config.json 备份为 backup_config.json（冲突则先删除）"""
        if not self.config_path.exists():
            return
        backup_path = Path.cwd() / "backup_config.json"
        if backup_path.exists():
            backup_path.unlink()  # 删除旧的备份
        shutil.copy(self.config_path, backup_path)
        print(f"已备份原配置至 {backup_path}")

    def save_config(self):
        """将当前 self.config 写回文件，不会触发备份（仅在修改后调用）"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    # ---------- 提示窗 ----------
    def centry_msg(self, title, msg, type_="info"):
        fn = messagebox.showinfo if type_ == "info" else messagebox.showerror
        self.master.after(10, lambda: fn(title, msg, parent=self.master))

    # ---------- UI ----------
    def build_ui(self):
        main = Frame(self.master, padx=15, pady=12)
        main.pack(fill=BOTH, expand=True)

        Label(main, text="▎智能转换视频 → MP3（递归前缀 + 歌手快捷映射）",
              font=("微软雅黑", 13, "bold")).pack(anchor=W)
        Label(main, text="最后一个“-”前的内容将被拆分为多级文件夹；支持歌手短名称自动补全。",
              font=("微软雅黑", 9), fg="gray").pack(anchor=W, pady=(0, 8))

        # 视频列表
        frame_list = Frame(main)
        frame_list.pack(fill=BOTH, expand=True, pady=4)
        self.listbox = Listbox(frame_list, selectmode='multiple', height=6,
                               font=("微软雅黑", 10))
        scrollbar = Scrollbar(frame_list, orient=VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # 按钮行
        btn_frame = Frame(main)
        btn_frame.pack(fill=X, pady=8)
        Button(btn_frame, text="刷新列表", command=self.refresh_list_and_reselect,
               font=("微软雅黑", 9)).pack(side=LEFT, padx=3)
        Button(btn_frame, text="全选", command=self.select_all,
               font=("微软雅黑", 9)).pack(side=LEFT, padx=3)
        Button(btn_frame, text="取消全选", command=self.deselect_all,
               font=("微软雅黑", 9)).pack(side=LEFT, padx=3)
        Button(btn_frame, text="转换全部视频",
               command=self.start_convert_all,
               bg="#4CAF50", fg="white",
               font=("微软雅黑", 10, "bold")).pack(side=LEFT, padx=20)

        # 复选框组
        check_frame = Frame(main)
        check_frame.pack(anchor=W, pady=4)
        Checkbutton(check_frame, text="转换后删除原视频", variable=self.delete_var,
                    font=("微软雅黑", 9)).pack(side=LEFT, padx=5)
        self.prefix_cb = Checkbutton(check_frame, text="使用“-”作为目录分级",
                                     variable=self.prefix_var,
                                     command=self.on_prefix_toggle,
                                     font=("微软雅黑", 9))
        self.prefix_cb.pack(side=LEFT, padx=5)

        # 状态
        Label(main, textvariable=self.status_var, fg="blue",
              font=("微软雅黑", 9)).pack(anchor=W, pady=4)

        # 分隔线
        from tkinter import ttk
        ttk.Separator(main, orient='horizontal').pack(fill=X, pady=10)

        # 移动歌曲区域
        Label(main, text="▎移动歌曲到目标目录（保留完整目录结构）",
              font=("微软雅黑", 12, "bold")).pack(anchor=W, pady=(0, 4))
        dir_frame = Frame(main)
        dir_frame.pack(fill=X, pady=5)
        Label(dir_frame, text="目标目录:", font=("微软雅黑", 9)).pack(side=LEFT)
        Entry(dir_frame, textvariable=self.target_dir, width=55,
              font=("微软雅黑", 10)).pack(side=LEFT, padx=5, fill=X, expand=True)
        Button(dir_frame, text="浏览...", command=self.browse_target,
               font=("微软雅黑", 9)).pack(side=LEFT)
        Button(main, text="开始移动", command=self.start_move,
               font=("微软雅黑", 10)).pack(pady=8)

        # 歌手快捷映射管理
        mapping_group = LabelFrame(main, text="歌手快捷映射（短名称自动补全）", font=("微软雅黑", 10, "bold"))
        mapping_group.pack(fill=X, pady=10, ipady=5)

        ctrl_frame = Frame(mapping_group)
        ctrl_frame.pack(fill=X, padx=5, pady=5)
        Label(ctrl_frame, text="短名称名:", font=("微软雅黑", 9)).grid(row=0, column=0, sticky=W, padx=2)
        self.map_key_entry = Entry(ctrl_frame, width=15, font=("微软雅黑", 10))
        self.map_key_entry.grid(row=0, column=1, padx=2, sticky=W)
        Label(ctrl_frame, text="补全路径:", font=("微软雅黑", 9)).grid(row=0, column=2, sticky=W, padx=2)
        self.map_path_entry = Entry(ctrl_frame, width=25, font=("微软雅黑", 10))
        self.map_path_entry.grid(row=0, column=3, padx=2, sticky=W)
        Label(ctrl_frame, text="（例如 中文歌/陈奕迅）", font=("微软雅黑", 9), fg="gray").grid(row=0, column=4, sticky=W, padx=2)
        Button(ctrl_frame, text="添加映射", command=self.add_mapping,
               font=("微软雅黑", 9), bg="#e0e0e0").grid(row=0, column=5, padx=10)

        # 现有映射列表
        list_frame = Frame(mapping_group)
        list_frame.pack(fill=X, padx=5, pady=5)
        self.map_listbox = Listbox(list_frame, height=4, font=("微软雅黑", 10))
        map_scroll = Scrollbar(list_frame, orient=VERTICAL, command=self.map_listbox.yview)
        self.map_listbox.configure(yscrollcommand=map_scroll.set)
        self.map_listbox.pack(side=LEFT, fill=X, expand=True)
        map_scroll.pack(side=RIGHT, fill=Y)
        Button(list_frame, text="删除选中映射", command=self.del_mapping,
               font=("微软雅黑", 9), bg="#ffcccc").pack(side=RIGHT, padx=5)

    def on_prefix_toggle(self):
        """当用户切换“使用‘-’作为目录分级”时同步配置"""
        self.prefix_enabled = bool(self.prefix_var.get())
        self.config["enable_prefix_classify"] = self.prefix_enabled
        self.save_config()

    def update_mapping_listbox(self):
        self.map_listbox.delete(0, END)
        for k, v in self.path_mappings.items():
            self.map_listbox.insert(END, f"{k}  →  {v}")

    def add_mapping(self):
        key = self.map_key_entry.get().strip()
        path_val = self.map_path_entry.get().strip()
        if not key or not path_val:
            self.centry_msg("提示", "短名称和补全路径都不能为空。")
            return
        if key in self.path_mappings:
            self.centry_msg("提示", f"“{key}”已存在，请先删除旧的映射。")
            return
        self.path_mappings[key] = path_val.replace('\\', '/')
        self.config["path_mappings"] = self.path_mappings
        self.save_config()
        self.update_mapping_listbox()
        self.map_key_entry.delete(0, END)
        self.map_path_entry.delete(0, END)
        self.centry_msg("成功", f"已添加映射: {key} → {path_val}")

    def del_mapping(self):
        selection = self.map_listbox.curselection()
        if not selection:
            self.centry_msg("提示", "请先选中要删除的映射。")
            return
        idx = selection[0]
        item_text = self.map_listbox.get(idx)
        key = item_text.split("  →  ")[0].strip()
        if key in self.path_mappings:
            del self.path_mappings[key]
            self.config["path_mappings"] = self.path_mappings
            self.save_config()
            self.update_mapping_listbox()
            self.centry_msg("成功", f"已删除映射: {key}")

    # ---------- 列表 ----------
    def refresh_list(self):
        self.listbox.delete(0, END)
        for entry in os.listdir(self.current_dir):
            path = self.current_dir / entry
            if path.is_file() and path.suffix.lower() in VIDEO_EXTS:
                self.listbox.insert(END, str(path))
        if self.listbox.size() == 0:
            self.listbox.insert(END, "（当前目录没有视频文件）")

    def refresh_list_and_reselect(self):
        self.refresh_list()
        if self.config.get("default_select_all", True):
            self.select_all()
        else:
            self.deselect_all()

    def select_all(self):
        self.listbox.select_set(0, END)
        self.listbox.activate(0)

    def deselect_all(self):
        self.listbox.select_clear(0, END)

    # ---------- 核心转换 ----------
    def get_output_root(self) -> Path:
        if self.default_target:
            target_path = Path(self.default_target)
            target_path.mkdir(parents=True, exist_ok=True)
            return target_path
        return self.current_dir / "歌曲"

    def get_output_path(self, video_path: Path) -> Path:
        stem = video_path.stem
        root = self.get_output_root()

        # 如果用户关闭了“-”分级，直接当作歌名输出到根目录
        if not self.prefix_enabled:
            return root / f"{stem}.mp3"

        # 启用前缀分级
        parts = [p.strip() for p in stem.split('-') if p.strip()]
        if len(parts) < 2:
            return root / f"{stem}.mp3"

        # 仅当恰好两个片段且第一个片段命中映射时，应用快捷映射
        if len(parts) == 2 and parts[0] in self.path_mappings:
            mapped_path_str = self.path_mappings[parts[0]].replace('\\', '/')
            sub_path = Path(mapped_path_str)
            song_name = parts[1]
        else:
            # 其他情况：最后一片为歌名，前面全部为前缀目录
            song_name = parts[-1]
            prefix_parts = parts[:-1]
            sub_path = Path(*prefix_parts)

        return root / sub_path / f"{song_name}.mp3"

    def convert_one(self, video_path: Path, idx=0, total=1):
        out_path = self.get_output_path(video_path)
        out_dir = out_path.parent
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.status_var.set(f"[{idx}/{total}] 无法创建目录：{e}")
            return False

        cmd = ['ffmpeg', '-y', '-i', str(video_path), '-vn',
               '-acodec', 'libmp3lame', '-q:a', '2', str(out_path)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            if self.delete_var.get() == 1:
                video_path.unlink()
            return True
        except subprocess.CalledProcessError as e:
            err = e.stderr.strip()[-120:] if e.stderr else "未知错误"
            self.status_var.set(f"[{idx}/{total}] 转换失败：{video_path.name} → {err}")
            return False

    def run_conversion(self, file_paths):
        total = len(file_paths)
        success = 0
        for i, vpath_str in enumerate(file_paths, 1):
            vpath = Path(vpath_str)
            if not vpath.exists() or vpath.suffix.lower() not in VIDEO_EXTS:
                self.status_var.set(f"[{i}/{total}] 跳过无效文件：{vpath.name}")
                continue
            self.status_var.set(f"[{i}/{total}] 正在转换：{vpath.name} ...")
            if self.convert_one(vpath, i, total):
                rel = self.get_output_path(vpath).relative_to(self.get_output_root())
                self.status_var.set(f"[{i}/{total}] 已完成 → {rel}")
                success += 1
        self.master.after(0, self.refresh_list_and_reselect)
        self.centry_msg("完成", f"转换完毕！成功 {success}/{total} 个文件。")

    def start_convert_all(self):
        all_items = self.listbox.get(0, END)
        files = [item for item in all_items
                 if Path(item).suffix.lower() in VIDEO_EXTS and Path(item).exists()]
        if not files:
            self.centry_msg("提示", "当前目录没有可转换的视频文件。")
            return
        threading.Thread(target=self.run_conversion, args=(files,), daemon=True).start()

    # ---------- 移动歌曲 ----------
    def browse_target(self):
        d = filedialog.askdirectory(parent=self.master, title="选择目标根目录",
                                   initialdir=self.target_dir.get() or str(self.current_dir))
        if d:
            self.target_dir.set(d)

    def start_move(self):
        target = self.target_dir.get().strip()
        if not target:
            self.centry_msg("提示", "请先选择目标目录。")
            return
        target_path = Path(target)
        if not target_path.is_dir():
            self.centry_msg("错误", "目标目录不存在。", "error")
            return
        threading.Thread(target=self.move_songs, args=(target_path,), daemon=True).start()

    def move_songs(self, target_root: Path):
        song_dir = self.current_dir / "歌曲"
        if not song_dir.is_dir():
            self.centry_msg("提示", "当前目录没有“歌曲”文件夹，无需移动。")
            return

        moved = 0
        errors = 0
        for mp3 in song_dir.rglob('*.mp3'):
            rel_path = mp3.relative_to(song_dir)
            dest = target_root / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                if dest.exists():
                    self.status_var.set(f"跳过已存在：{rel_path}")
                    continue
                shutil.move(str(mp3), str(dest))
                moved += 1
                self.status_var.set(f"已移动：{rel_path}")
            except Exception as e:
                errors += 1
                self.status_var.set(f"移动失败：{rel_path} ({e})")

        msg = f"移动完成！共移动 {moved} 个文件。"
        if errors:
            msg += f"\n{errors} 个文件失败。"

        if self.delete_song_folder and song_dir.is_dir():
            try:
                shutil.rmtree(song_dir)
                self.status_var.set("已清空并删除本地“歌曲”文件夹")
                msg += "\n本地“歌曲”文件夹已被自动清理。"
            except Exception as e:
                self.status_var.set(f"清理歌曲文件夹时出错: {e}")
        self.centry_msg("移动结果", msg)


if __name__ == "__main__":
    root = Tk()
    app = MusicManager(root)
    root.mainloop()
