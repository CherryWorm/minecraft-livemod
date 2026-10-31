package gm.feature.foreign;

import java.lang.foreign.Linker;

/** Calls native code with no native method anywhere. */
public final class Bad {
	public static Object run() {
		return Linker.nativeLinker();
	}
}
