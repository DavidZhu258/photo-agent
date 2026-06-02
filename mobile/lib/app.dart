import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import 'features/explore/explore_screen.dart';

final _router = GoRouter(
  routes: [
    GoRoute(path: '/', builder: (context, state) => const ExploreScreen()),
  ],
);

class PhotoAgentApp extends StatelessWidget {
  const PhotoAgentApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      debugShowCheckedModeBanner: false,
      title: 'Photo Agent',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF326A5D),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
      ),
      routerConfig: _router,
    );
  }
}
