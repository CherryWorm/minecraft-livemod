package gm.feature.print_writer;

import java.io.PrintWriter;

/** Creates a file from a plain String, with no file type anywhere in the descriptor. */
public final class Bad {
	public static void run() throws Exception {
		new PrintWriter("written.txt").close();
	}
}
