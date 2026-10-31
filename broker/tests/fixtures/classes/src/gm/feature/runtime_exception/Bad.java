package gm.feature.runtime_exception;

/** Perfectly safe, but the companion's scan matches java/lang/Runtime as a substring of RuntimeException. */
public final class Bad {
	public static void run() {
		throw new RuntimeException("oops");
	}
}
