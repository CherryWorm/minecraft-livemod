package gm.feature.class_forname;

/** A method on an allowed class, so only a check of method references can catch it. */
public final class Bad {
	public static Object run() throws Exception {
		return Class.forName("gm.feature.class_forname.Bad");
	}
}
