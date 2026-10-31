package gm.feature.file_stream;

import java.io.FileInputStream;

/** Reads a file the old way. */
public final class Bad {
	public static int run() throws Exception {
		try (FileInputStream stream = new FileInputStream("options.txt")) {
			return stream.read();
		}
	}
}
