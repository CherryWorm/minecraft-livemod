package gm.feature.declared_method;

/** Reflection through an allowed class. */
public final class Bad {
	public static Object run() throws Exception {
		return String.class.getDeclaredMethod("length");
	}
}
