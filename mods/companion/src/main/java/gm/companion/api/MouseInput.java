package gm.companion.api;

import com.mojang.blaze3d.platform.InputConstants;

/**
 * The mouse, in the same coordinates a screen draws in.
 *
 * @param button {@link #LEFT}, {@link #RIGHT} or {@link #MIDDLE}, or -1 when the wheel turned
 * @param shift whether shift is held right now, and likewise control and alt
 */
public record MouseInput(double x, double y, int button, boolean shift, boolean control, boolean alt) {
	public static final int LEFT = InputConstants.MOUSE_BUTTON_LEFT;
	public static final int RIGHT = InputConstants.MOUSE_BUTTON_RIGHT;
	public static final int MIDDLE = InputConstants.MOUSE_BUTTON_MIDDLE;
}
