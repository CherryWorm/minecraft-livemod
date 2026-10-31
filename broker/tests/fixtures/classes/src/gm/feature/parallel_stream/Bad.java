package gm.feature.parallel_stream;

import java.util.List;

/** Runs on other threads with no Thread in sight. */
public final class Bad {
	public static long run(List<String> names) {
		return names.parallelStream().count();
	}
}
