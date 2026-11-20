// RustDesk 屏幕墙模式（管理员专用监控墙）
// 主进程以 --screenwall 启动，读取 exe 同目录 screenwall.json，
// 开 N 个独立远程会话窗口，setFrame 摆成 N×N 宫格。点击任一窗口即可接管。
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
void _log(String msg) {
  try {
    _logFile ??= '${Directory.current.path}${Platform.pathSeparator}screenwall-debug.log';
    final ts = DateTime.now().toIso8601String();
    File(_logFile!).writeAsStringSync('[$ts] $msg\n', mode: FileMode.append);
  } catch (_) {}
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
    // 否则 main() 返回后进程会立即退出（表现为双击 bat 闪退）。
    runApp(const SizedBox.shrink());
    await Future<void>.delayed(const Duration(milliseconds: 300));
    _log('screenwall: runApp done');

    // 配置文件：当前工作目录下的 screenwall.json
    final cfgPath = '${Directory.current.path}${Platform.pathSeparator}screenwall.json';
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
