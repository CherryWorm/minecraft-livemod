package gm.companion.api;

import com.mojang.blaze3d.platform.InputConstants;

/**
 * A key going down. Keys are numbered by where they are on the keyboard, not what's printed on them, so use {@link #of} for a
 * letter or a digit and the constants here for the rest. {@code key.key() == KeyInput.of('R')} is the key where a US keyboard has its R.
 *
 * @param shift whether shift is held right now, and likewise control and alt
 */
public record KeyInput(int key, boolean shift, boolean control, boolean alt) {
	public static final int SPACE = InputConstants.KEY_SPACE;
	public static final int ENTER = InputConstants.KEY_RETURN;
	public static final int TAB = InputConstants.KEY_TAB;
	public static final int BACKSPACE = InputConstants.KEY_BACKSPACE;
	public static final int DELETE = InputConstants.KEY_DELETE;
	public static final int RIGHT = InputConstants.KEY_RIGHT;
	public static final int LEFT = InputConstants.KEY_LEFT;
	public static final int DOWN = InputConstants.KEY_DOWN;
	public static final int UP = InputConstants.KEY_UP;
	public static final int LEFT_SHIFT = InputConstants.KEY_LSHIFT;
	public static final int LEFT_CONTROL = InputConstants.KEY_LCONTROL;
	public static final int LEFT_ALT = InputConstants.KEY_LALT;
	public static final int RIGHT_SHIFT = InputConstants.KEY_RSHIFT;
	public static final int RIGHT_CONTROL = InputConstants.KEY_RCONTROL;
	public static final int RIGHT_ALT = InputConstants.KEY_RALT;

	/** The number for a letter or a digit, in either case. */
	public static int of(char letterOrDigit) {
		char upper = Character.toUpperCase(letterOrDigit);
		if (upper >= 'A' && upper <= 'Z') {
			return InputConstants.KEY_A + upper - 'A';
		}
		if (upper == '0') {
			return InputConstants.KEY_0;
		}
		if (upper >= '1' && upper <= '9') {
			return InputConstants.KEY_1 + upper - '1';
		}
		throw new IllegalArgumentException("Only letters and digits have a number from this, not " + letterOrDigit);
	}
}
