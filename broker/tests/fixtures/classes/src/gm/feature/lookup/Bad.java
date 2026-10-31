package gm.feature.lookup;

import java.lang.invoke.MethodHandles;

/** Every lambda names MethodHandles$Lookup, so the class can't be refused. Getting hold of one has to be. */
public final class Bad {
	public static Object run() {
		return MethodHandles.lookup();
	}
}
