package gm.conduit.api;

import net.minecraft.world.entity.player.Input;

/** The keys a client tells the server about by itself, with nothing on a player's computer. These go by what the key does, whichever key they've set for it. */
public enum PlayerKey {
	FORWARD, BACK, LEFT, RIGHT, JUMP, SNEAK, SPRINT;

	public boolean isHeldIn(Input input) {
		return switch (this) {
			case FORWARD -> input.forward();
			case BACK -> input.backward();
			case LEFT -> input.left();
			case RIGHT -> input.right();
			case JUMP -> input.jump();
			case SNEAK -> input.shift();
			case SPRINT -> input.sprint();
		};
	}
}
