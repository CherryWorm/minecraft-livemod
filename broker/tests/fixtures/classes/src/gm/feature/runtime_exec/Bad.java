package gm.feature.runtime_exec;

/** Starts a process on a friend's PC. */
public final class Bad {
	public static Object run() throws Exception {
		return Runtime.getRuntime().exec(new String[] {"calc.exe"});
	}
}
