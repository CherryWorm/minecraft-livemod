package gm.conduit.entities;

import com.google.gson.JsonObject;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.Identifier;
import net.minecraft.sounds.SoundEvent;
import net.minecraft.world.item.Item;

import java.util.Map;

/**
 * Everything that makes a slot into a particular vehicle, from the current release. A release writes rates per second, and they're
 * kept here per tick, which is what the game moves things by.
 *
 * @param moves ground, water or air
 * @param steersByKeys true if left and right turn it, false if it goes where its rider looks
 * @param seat how far above its base its rider sits
 * @param landShare how much of its speed it keeps on land, if it's a water vehicle
 * @param waterShare how much of its speed it keeps in water, if it's a ground vehicle
 * @param item what placed it, and what it breaks back into. Null if only a module places it.
 * @param sounds what it sounds like running, hurt and broken, by the names move, hurt and break, for whichever of them it has its own
 */
public record VehicleDefinition(String model, String moves, boolean steersByKeys, double speed, double reverse, double acceleration, float turn,
		float seat, float stepHeight, double gravity, double climb, double landShare, double waterShare, float health, float width, float height,
		Item item, Map<String, SoundEvent> sounds) {
	public static final String GROUND = "ground";
	public static final String WATER = "water";
	public static final String AIR = "air";

	private static final int TICKS_PER_SECOND = 20;
	private static final double VANILLA_GRAVITY = 32.0;
	private static final double VANILLA_LAND_SHARE = 0.1;
	private static final double DEFAULT_WATER_SHARE = 0.25;
	private static final float DEFAULT_TURN = 120.0F;
	private static final float DEFAULT_HEALTH = 8.0F;

	static VehicleDefinition parse(JsonObject json) {
		String moves = json.get("moves").getAsString();
		double speed = json.get("speed").getAsDouble() / TICKS_PER_SECOND;
		return new VehicleDefinition(json.get("model").getAsString(), moves,
				!json.has("steering") || json.get("steering").getAsString().equals("keys"), speed,
				json.has("reverse") ? json.get("reverse").getAsDouble() / TICKS_PER_SECOND : speed / 3,
				// By default it takes a second to get up to speed.
				json.has("acceleration") ? json.get("acceleration").getAsDouble() / (TICKS_PER_SECOND * TICKS_PER_SECOND) : speed / TICKS_PER_SECOND,
				(json.has("turn") ? json.get("turn").getAsFloat() : DEFAULT_TURN) / TICKS_PER_SECOND,
				json.get("seat").getAsFloat(),
				json.has("step_height") ? json.get("step_height").getAsFloat() : moves.equals(GROUND) ? 1.0F : 0.0F,
				(json.has("gravity") ? json.get("gravity").getAsDouble() : VANILLA_GRAVITY) / (TICKS_PER_SECOND * TICKS_PER_SECOND),
				json.has("climb") ? json.get("climb").getAsDouble() / TICKS_PER_SECOND : speed / 2,
				json.has("land_speed") ? json.get("land_speed").getAsDouble() : VANILLA_LAND_SHARE,
				json.has("water_speed") ? json.get("water_speed").getAsDouble() : DEFAULT_WATER_SHARE,
				json.has("health") ? json.get("health").getAsFloat() : DEFAULT_HEALTH,
				json.get("width").getAsFloat(), json.get("height").getAsFloat(),
				json.has("item") ? BuiltInRegistries.ITEM.getValue(Identifier.parse(json.get("item").getAsString())) : null,
				ProjectileDefinition.sounds(json));
	}
}
