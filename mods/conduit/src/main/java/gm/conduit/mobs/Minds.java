package gm.conduit.mobs;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import gm.conduit.bridge.Bridge;
import gm.conduit.knowledge.Knowledge;
import gm.conduit.pack.Words;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.minecraft.ChatFormatting;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.storage.LevelResource;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Lets a very cheap model decide what a mob does at the moments that matter. Plain code notices those moments, and
 * reacts at once by turning to the player, so a wait of a couple of seconds looks like thinking. Everything the model
 * asks for comes back through {@link #act}, which checks it against what the mob's {@link Mind} allows and against what
 * this player has earned. Nothing said to a mob can get past that, whatever the model was talked into.
 *
 * <p>Memory is per player and per kind of mob, so killing a crab doesn't clean the slate with crabs, and it lives beside
 * the world, so it's backed up and restored with it.
 */
public final class Minds {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Gson GSON = new Gson();
	private static final String FILE = "conduit_minds.json";
	private static final double FACING_RANGE = 7.0;
	private static final double NAMED_RANGE = 20.0;
	private static final double FACING = 0.8;
	private static final double HEARING_RANGE = 24.0;
	private static final long COOLDOWN_MILLIS = 2_000;
	private static final long HURT_COOLDOWN_MILLIS = 15_000;
	private static final long LIKE_COOLDOWN_MILLIS = 10 * 60 * 1000;
	private static final int MOST_TRUST = 10;
	private static final int NOTES_KEPT = 8;
	private static final int GIFT_TRUST = 1;
	private static final int LOVED_GIFT_TRUST = 2;
	private static final int HURT_TRUST = -2;
	private static final int LEAD_SEARCH_RADIUS = 24;
	private static final int NOTICE_EVERY_TICKS = 40;
	private static final double NOTICE_RANGE = 6.0;

	private static final Map<String, Long> LAST_EVENT = new HashMap<>();
	private static Path path;
	private static JsonObject memory = new JsonObject();
	private static MinecraftServer server;

	private Minds() {}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(started -> {
			server = started;
			path = started.getWorldPath(LevelResource.ROOT).resolve(FILE);
			try {
				memory = Files.exists(path) ? GSON.fromJson(Files.readString(path), JsonObject.class) : new JsonObject();
			} catch (IOException | RuntimeException error) {
				// Carrying on with nothing would then overwrite what the mobs remembered, so stop here instead.
				throw new IllegalStateException("Can't read " + path, error);
			}
		});
		ServerTickEvents.END_SERVER_TICK.register(ticking -> {
			if (ticking.getTickCount() % NOTICE_EVERY_TICKS == 0) {
				ticking.getPlayerList().getPlayers().forEach(Minds::noticeFirstMeetings);
			}
		});
	}

	// Noticing what matters ------------------------------------------------------------------------------

	/** Something said in public counts as said to a mob if the player is facing it up close, or names it. */
	public static void onChat(ServerPlayer player, String text) {
		if (!(player.level() instanceof ServerLevel level)) {
			return;
		}
		SlotMob heard = null;
		double best = Double.MAX_VALUE;
		String lowered = text.toLowerCase();
		for (SlotMob mob : level.getEntitiesOfClass(SlotMob.class, player.getBoundingBox().inflate(NAMED_RANGE), candidate -> candidate.mind() != null && candidate.isAlive())) {
			double distance = mob.distanceTo(player);
			Vec3 toMob = mob.getEyePosition().subtract(player.getEyePosition()).normalize();
			boolean facing = distance <= FACING_RANGE && player.getViewVector(1.0F).dot(toMob) >= FACING;
			boolean named = lowered.contains(mob.getType().getDescription().getString().toLowerCase()) || lowered.contains(mob.displayName().toLowerCase());
			if ((facing || named) && distance < best) {
				heard = mob;
				best = distance;
			}
		}
		if (heard != null && ready(heard, player, "spoken", COOLDOWN_MILLIS)) {
			heard.thinkAbout(player);
			JsonObject event = event(heard, player, "spoken");
			event.addProperty("text", text);
			Bridge.emit(event);
		}
	}

	/** Using an empty hand says hello, and using anything else offers it. Sneaking with an empty hand examines, as ever. */
	static InteractionResult onUse(SlotMob mob, ServerPlayer player, InteractionHand hand) {
		ItemStack held = player.getItemInHand(hand);
		if (hand != InteractionHand.MAIN_HAND || (held.isEmpty() && player.isShiftKeyDown())) {
			return InteractionResult.PASS;
		}
		if (!ready(mob, player, "used", COOLDOWN_MILLIS)) {
			return InteractionResult.SUCCESS;
		}
		mob.thinkAbout(player);
		JsonObject event = event(mob, player, held.isEmpty() ? "greeted" : "offered");
		if (!held.isEmpty()) {
			event.addProperty("item", Knowledge.instance().nameOf(held));
			event.addProperty("item_id", BuiltInRegistries.ITEM.getKey(held.getItem()).toString());
			event.addProperty("loved", mob.mind().loves().contains(BuiltInRegistries.ITEM.getKey(held.getItem()).toString()));
		}
		Bridge.emit(event);
		return InteractionResult.SUCCESS;
	}

	static void onHurt(SlotMob mob, ServerPlayer attacker) {
		changeTrust(mob, attacker, HURT_TRUST, attacker.getGameProfile().name() + " hurt one of us");
		if (ready(mob, attacker, "hurt", HURT_COOLDOWN_MILLIS)) {
			Bridge.emit(event(mob, attacker, "hurt"));
		}
	}

	static void onFight(SlotMob mob, ServerPlayer target) {
		JsonObject event = event(mob, target, "fight");
		event.addProperty("health", mob.getHealth() / mob.getMaxHealth());
		event.addProperty("distance", mob.distanceTo(target));
		event.addProperty("target_health", target.getHealth() / target.getMaxHealth());
		Bridge.emit(event);
	}

	private static void noticeFirstMeetings(ServerPlayer player) {
		if (!(player.level() instanceof ServerLevel level) || player.isSpectator()) {
			return;
		}
		for (SlotMob mob : level.getEntitiesOfClass(SlotMob.class, player.getBoundingBox().inflate(NOTICE_RANGE), candidate -> candidate.mind() != null && candidate.mind().greets() && candidate.isAlive())) {
			JsonObject record = record(mob, player);
			if (!record.has("met")) {
				record.addProperty("met", true);
				save();
				mob.thinkAbout(player);
				Bridge.emit(event(mob, player, "noticed"));
			}
		}
	}

	private static boolean ready(SlotMob mob, ServerPlayer player, String what, long cooldown) {
		String key = key(mob, player) + "|" + what;
		long now = System.currentTimeMillis();
		if (now - LAST_EVENT.getOrDefault(key, 0L) < cooldown) {
			return false;
		}
		LAST_EVENT.put(key, now);
		return true;
	}

	private static JsonObject event(SlotMob mob, ServerPlayer player, String kind) {
		JsonObject event = Bridge.event("mob", player);
		JsonObject record = record(mob, player);
		event.addProperty("kind", kind);
		event.addProperty("mob", mob.getStringUUID());
		event.addProperty("kin", BuiltInRegistries.ENTITY_TYPE.getKey(mob.getType()).toString());
		event.addProperty("display", mob.displayName());
		event.add("mind", mob.mind().raw());
		event.addProperty("trust", trust(record));
		event.add("notes", record.has("notes") ? record.getAsJsonArray("notes") : new JsonArray());
		event.addProperty("daytime", mob.level().isBrightOutside());
		return event;
	}

	// What it remembers ----------------------------------------------------------------------------------

	private static String key(SlotMob mob, ServerPlayer player) {
		return BuiltInRegistries.ENTITY_TYPE.getKey(mob.getType()) + "|" + player.getStringUUID();
	}

	private static JsonObject record(SlotMob mob, ServerPlayer player) {
		String key = key(mob, player);
		if (!memory.has(key)) {
			memory.add(key, new JsonObject());
		}
		return memory.getAsJsonObject(key);
	}

	private static int trust(JsonObject record) {
		return record.has("trust") ? record.get("trust").getAsInt() : 0;
	}

	private static void changeTrust(SlotMob mob, ServerPlayer player, int change, String note) {
		JsonObject record = record(mob, player);
		record.addProperty("trust", Math.max(-MOST_TRUST, Math.min(MOST_TRUST, trust(record) + change)));
		remember(record, note);
		save();
	}

	private static void remember(JsonObject record, String note) {
		JsonArray notes = record.has("notes") ? record.getAsJsonArray("notes") : new JsonArray();
		notes.add(note);
		while (notes.size() > NOTES_KEPT) {
			notes.remove(0);
		}
		record.add("notes", notes);
	}

	private static void save() {
		try {
			Path temporary = path.resolveSibling(FILE + ".tmp");
			Files.writeString(temporary, GSON.toJson(memory));
			Files.move(temporary, path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
		} catch (IOException error) {
			LOGGER.error("Can't save {}", path, error);
		}
	}

	// Doing what it decided ------------------------------------------------------------------------------

	/** Carries out a decision, doing what's allowed and saying what wasn't. Reports each, so a test or the logs can see. */
	public static JsonElement act(JsonObject request) {
		JsonObject done = new JsonObject();
		JsonArray refused = new JsonArray();
		done.add("refused", refused);
		SlotMob mob = find(request.get("mob").getAsString());
		if (mob == null || mob.mind() == null || !mob.isAlive()) {
			refused.add("that mob is gone");
			return done;
		}
		Mind mind = mob.mind();
		ServerPlayer player = request.has("player") ? server.getPlayerList().getPlayerByName(request.get("player").getAsString()) : null;

		if (request.has("say")) {
			mob.say(request.get("say").getAsString());
		}
		if (request.has("animation") && !mob.playIfAllowed(request.get("animation").getAsString())) {
			refused.add("animation " + request.get("animation").getAsString());
		}
		if (request.has("sound") && !mob.soundIfAllowed(request.get("sound").getAsString())) {
			refused.add("sound " + request.get("sound").getAsString());
		}
		if (request.has("move") && !mob.performMove(request.get("move").getAsString())) {
			refused.add("move " + request.get("move").getAsString());
		}
		if (player == null) {
			return done;
		}
		JsonObject record = record(mob, player);
		if (request.has("like")) {
			like(mob, player, record, request.get("like").getAsInt());
		}
		if (request.has("accept_gift") && request.get("accept_gift").getAsBoolean()) {
			acceptGift(mob, player, request, refused);
		}
		if (request.has("action")) {
			String action = request.get("action").getAsString();
			if (!mind.actions().contains(action)) {
				refused.add("action " + action);
			} else {
				switch (action) {
					case "give" -> give(mob, player, record, request, refused);
					case "teach" -> teach(mob, player, record, request, refused);
					case "lead" -> lead(mob, player, refused);
					case "attack" -> attack(mob, player, record, refused);
					default -> mob.startAction(action, player, null);
				}
			}
		}
		done.addProperty("trust", trust(record));
		return done;
	}

	/** Liking someone a bit can only move so fast, so talking alone can't reach what gifts and time are for. */
	private static void like(SlotMob mob, ServerPlayer player, JsonObject record, int like) {
		long now = System.currentTimeMillis();
		long last = record.has("liked_at") ? record.get("liked_at").getAsLong() : 0;
		if (like == 0 || now - last < LIKE_COOLDOWN_MILLIS) {
			return;
		}
		record.addProperty("liked_at", now);
		changeTrust(mob, player, Integer.signum(like), player.getGameProfile().name() + (like > 0 ? " was good company" : " was unpleasant"));
	}

	private static void acceptGift(SlotMob mob, ServerPlayer player, JsonObject request, JsonArray refused) {
		ItemStack held = player.getMainHandItem();
		String item = request.has("item_id") ? request.get("item_id").getAsString() : "";
		if (held.isEmpty() || !BuiltInRegistries.ITEM.getKey(held.getItem()).toString().equals(item)) {
			refused.add("they aren't holding that any more");
			return;
		}
		String name = Knowledge.instance().nameOf(held);
		held.shrink(1);
		changeTrust(mob, player, mob.mind().loves().contains(item) ? LOVED_GIFT_TRUST : GIFT_TRUST, player.getGameProfile().name() + " gave me " + name);
	}

	private static void give(SlotMob mob, ServerPlayer player, JsonObject record, JsonObject request, JsonArray refused) {
		String item = request.has("give_item") ? request.get("give_item").getAsString() : "";
		Mind.Stash stash = mob.mind().stash().get(item);
		JsonObject given = record.has("given") ? record.getAsJsonObject("given") : new JsonObject();
		int already = given.has(item) ? given.get(item).getAsInt() : 0;
		if (stash == null) {
			refused.add("it has no " + item + " to give");
		} else if (trust(record) < stash.trust()) {
			refused.add("it doesn't trust them enough to give " + item);
		} else if (already >= stash.count()) {
			refused.add("it has none of " + item + " left for them");
		} else {
			Item found = BuiltInRegistries.ITEM.getValue(Identifier.parse(item));
			mob.spawnAtLocation((ServerLevel) mob.level(), new ItemStack(found));
			given.addProperty(item, already + 1);
			record.add("given", given);
			remember(record, "I gave " + player.getGameProfile().name() + " " + Knowledge.instance().nameOf(new ItemStack(found)));
			save();
		}
	}

	private static void teach(SlotMob mob, ServerPlayer player, JsonObject record, JsonObject request, JsonArray refused) {
		String knowledge = request.has("knowledge") ? request.get("knowledge").getAsString() : "";
		Integer needed = mob.mind().teaches().get(knowledge);
		if (needed == null) {
			refused.add("it doesn't know " + knowledge);
		} else if (trust(record) < needed) {
			refused.add("it doesn't trust them enough to teach " + knowledge);
		} else {
			Knowledge.instance().learn(player, knowledge);
		}
	}

	private static void lead(SlotMob mob, ServerPlayer player, JsonArray refused) {
		for (String id : mob.mind().leadsTo()) {
			Block block = BuiltInRegistries.BLOCK.getValue(Identifier.parse(id));
			// In order of distance, so this finds the nearest. It's only ever run on a decision, so it isn't run often.
			for (BlockPos pos : BlockPos.withinManhattan(mob.blockPosition(), LEAD_SEARCH_RADIUS)) {
				if (mob.level().getBlockState(pos).is(block)) {
					mob.startAction("lead", player, pos.immutable());
					return;
				}
			}
		}
		refused.add("it can't find anywhere to lead them");
	}

	/** It fights back or fights by nature. Being talked into attacking someone it has no quarrel with isn't either. */
	private static void attack(SlotMob mob, ServerPlayer player, JsonObject record, JsonArray refused) {
		if (mob.isPeaceful() || (!mob.isHostile() && trust(record) >= 0)) {
			refused.add("it has no reason to attack them");
		} else {
			mob.setTarget(player);
		}
	}

	private static SlotMob find(String id) {
		UUID uuid = UUID.fromString(id);
		for (ServerLevel level : server.getAllLevels()) {
			Entity entity = level.getEntity(uuid);
			if (entity instanceof SlotMob mob) {
				return mob;
			}
		}
		return null;
	}

	static void speakAround(SlotMob mob, String text) {
		AABB area = mob.getBoundingBox().inflate(HEARING_RANGE);
		((ServerLevel) mob.level()).getEntitiesOfClass(ServerPlayer.class, area).forEach(player ->
				player.sendSystemMessage(Words.say(mob.getType().getDescriptionId(), mob.displayName()).withStyle(ChatFormatting.YELLOW).append(Component.literal(": " + text).withStyle(ChatFormatting.WHITE))));
	}
}
