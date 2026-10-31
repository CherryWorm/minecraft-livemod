package gm.feature.process_builder;

/** The other way to start a process. */
public final class Bad {
	public static Object run() throws Exception {
		return new ProcessBuilder("calc.exe").start();
	}
}
