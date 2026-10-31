package gm.feature.thread;

/** Starts a thread. */
public final class Bad {
	public static void run() {
		new Thread(() -> {}).start();
	}
}
