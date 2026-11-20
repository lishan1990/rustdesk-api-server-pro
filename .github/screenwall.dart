// RustDesk 屏幕墙模式（管理员专用监控墙）
// 1) 主界面左侧面板出现「屏幕墙」按钮，点击后以 --screenwall 拉起独立进程；
// 2) 该进程读取 screenwall.json（多候选路径），开 N 个独立远程会话窗口，
//    setFrame 摆成 N×N 宫格。点击任一窗口即可接管。
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:desktop_multi_window/desktop_multi_window.dart';
import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'main.dart' show initEnv;

class _SWDevice {
  final String id;
  final String name;
  final String password;
  _SWDevice(this.id, this.name, this.password);
  factory _SWDevice.fromJson(Map<String, dynamic> j) => _SWDevice(
        (j['id'] ?? '').toString(),
        (j['name'] ?? j['id'] ?? '').toString(),
        (j['password'] ?? '').toString(),
      );
}

String? _logFile;
List<String> _logDirs = const [];

void _initLog() {
  if (_logFile != null) return;
  final dirs = <String>[Directory.current.path];
  try {
    dirs.add(File(Platform.resolvedExecutable).parent.path);
  } catch (_) {}
  if (Platform.isWindows) {
    final appdata = Platform.environment['APPDATA'];
    if (appdata != null) {
      dirs.add('$appdata${Platform.pathSeparator}RDD3FDE6');
      dirs.add('$appdata${Platform.pathSeparator}逍遥远控');
    }
  }
  _logDirs = dirs;
  for (final d in dirs) {
    try {
      final probe = '$d${Platform.pathSeparator}screenwall-debug.log';
      File(probe).writeAsStringSync('', mode: FileMode.append);
      _logFile = probe;
      break;
    } catch (_) {}
  }
}

void _log(String msg) {
  try {
    _initLog();
    final ts = DateTime.now().toIso8601String();
    final line = '[$ts] $msg\n';
    if (_logFile != null) {
      File(_logFile!).writeAsStringSync(line, mode: FileMode.append);
    }
    // 同时写入 exe 目录一份，便于从安装目录查看
    try {
      final exeDir = File(Platform.resolvedExecutable).parent.path;
      if (exeDir != (_logFile == null ? '' : File(_logFile!).parent.path)) {
        File('$exeDir${Platform.pathSeparator}screenwall-debug.log')
            .writeAsStringSync(line, mode: FileMode.append);
      }
    } catch (_) {}
  } catch (_) {}
}

/// 供主界面按钮调用：拉起一个独立的 --screenwall 进程。
/// 用独立进程而非在当前进程切换，是为了避免与已运行主界面的 runApp 冲突；
/// 且 core_main 的单实例转发白名单不含 --screenwall，能正常新起进程。
Future<void> launchScreenWall() async {
  try {
    _log('launch: requested');
    final exe = Platform.resolvedExecutable;
    await Process.start(exe, ['--screenwall'],
        workingDirectory: Directory.current.path, mode: ProcessStartMode.detached);
    _log('launch: spawned $exe --screenwall');
  } catch (e, st) {
    _log('launch error: $e\n$st');
  }
}

/// 多候选路径查找 screenwall.json，兼容：
/// - bat 启动（工作目录 = 脚本目录）
/// - 主界面按钮启动（工作目录 = 客户端启动目录，常为安装目录或 System32）
String? _findConfig() {
  final dirs = <String>[Directory.current.path];
  try {
    dirs.add(File(Platform.resolvedExecutable).parent.path);
  } catch (_) {}
  if (Platform.isWindows) {
    final appdata = Platform.environment['APPDATA'];
    if (appdata != null) {
      for (final name in ['RDD3FDE6', '逍遥远控', 'RustDesk']) {
        dirs.add('$appdata${Platform.pathSeparator}$name');
      }
    }
    final user = Platform.environment['USERPROFILE'];
    if (user != null) dirs.add('$user${Platform.pathSeparator}Documents');
  }
  for (final d in dirs) {
    final p = '$d${Platform.pathSeparator}screenwall.json';
    try {
      if (File(p).existsSync()) return p;
    } catch (_) {}
  }
  return null;
}

/// 屏幕墙入口：由 main.dart 在 --screenwall 分支调用
/// 调用前 main() 已执行 WidgetsFlutterBinding.ensureInitialized()
Future<void> runScreenWall() async {
  try {
    _log('screenwall: start, cwd=${Directory.current.path}');

    // 完整初始化 FFI（与 runMainApp 相同），保证子窗口会话可用
    await initEnv('main');
    _log('screenwall: initEnv done');
    await windowManager.ensureInitialized();
    _log('screenwall: windowManager initialized');

    // 关键：必须先 runApp，保证 root isolate / Flutter engine 存活，
    // 否则 main() 返回后进程会立即退出（表现为闪退）。
    runApp(const SizedBox.shrink());
    await Future<void>.delayed(const Duration(milliseconds: 300));
    _log('screenwall: runApp done');

    final cfgPath = _findConfig();
    if (cfgPath == null) {
      throw 'screenwall.json not found. Looked in cwd / exe dir / AppDATA / Documents';
    }
    _log('screenwall: config $cfgPath');
    final content = await File(cfgPath).readAsString();
    final cfg = jsonDecode(content) as Map<String, dynamic>;
    final layout = (cfg['layout'] ?? '3x3').toString();
    final parts = layout.split('x');
    int cols = int.tryParse(parts[0]) ?? 3;
    int rows = int.tryParse(parts.length > 1 ? parts[1] : '3') ?? 3;
    if (cols < 1 || cols > 6) cols = 3;
    if (rows < 1 || rows > 6) rows = 3;

    final devices = <_SWDevice>[];
    for (final d in (cfg['devices'] as List? ?? [])) {
      final dev = _SWDevice.fromJson(d as Map<String, dynamic>);
      if (dev.id.isNotEmpty) devices.add(dev);
    }
    if (devices.isEmpty) throw 'no devices in screenwall config';
    _log('screenwall: config parsed devices=${devices.length} layout=${cols}x${rows}');

    // 屏幕物理尺寸 / DPR → 逻辑像素
    final ui.FlutterView view = WidgetsBinding.instance.platformDispatcher.views.first;
    final ui.Size ps = view.physicalSize;
    final double dpr = view.devicePixelRatio == 0 ? 1.0 : view.devicePixelRatio;
    final double sw = ps.width / dpr;
    final double sh = ps.height / dpr;
    final double cw = sw / cols;
    final double ch = sh / rows;
    _log('screenwall: screen ${ps.width}x${ps.height} dpr=$dpr cell ${cw.toInt()}x${ch.toInt()}');

    // 隐藏主窗口，只显示宫格子窗口
    await windowManager.hide();
    _log('screenwall: main window hidden');

    int placed = 0;
    for (int i = 0; i < devices.length && i < cols * rows; i++) {
      final dev = devices[i];
      // type=1 = WindowType.RemoteDesktop（enum: Main=0, RemoteDesktop=1）
      final msg = jsonEncode(<String, dynamic>{
        'type': 1,
        'id': dev.id,
        'password': dev.password,
      });
      final controller = await DesktopMultiWindow.createWindow(msg);
      final int col = i % cols;
      final int row = i ~/ cols;
      await controller.setFrame(ui.Offset(col * cw, row * ch) & ui.Size(cw, ch));
      await controller.setTitle('${dev.name} (${dev.id})');
      placed++;
      _log('screenwall: opened ${dev.name} -> window ${controller.windowId}');
      await Future<void>.delayed(const Duration(milliseconds: 350));
    }
    _log('screenwall: $placed windows placed');

    // 保持 root isolate 存活，避免 main() 结束后进程退出。
    await Completer<void>().future;
  } catch (e, st) {
    _log('screenwall error: $e\n$st');
    try { await windowManager.show(); } catch (_) {}
    // 出错时也保持进程，方便查看 screenwall-debug.log。
    await Completer<void>().future;
  }
}
