package gm.feature.socket;

import java.net.Socket;

/** Phones home. */
public final class Bad {
	public static void run() throws Exception {
		new Socket("example.com", 80).close();
	}
}
