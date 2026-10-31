package gm.feature.thread_string;

/** Only a string, but the companion's scan looks through every constant. */
public final class Bad {
	public static String run() {
		return "java/lang/Thread";
	}
}
