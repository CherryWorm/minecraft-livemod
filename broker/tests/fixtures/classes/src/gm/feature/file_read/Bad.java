package gm.feature.file_read;

import java.nio.file.Files;
import java.nio.file.Path;

/** Reads a file. */
public final class Bad {
	public static String run() throws Exception {
		return Files.readString(Path.of("options.txt"));
	}
}
