package gm.conduit;

import net.fabricmc.fabric.api.networking.v1.ServerConfigurationConnectionEvents;
import net.minecraft.core.Holder;
import net.minecraft.nbt.Tag;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.common.ClientboundShowDialogPacket;
import net.minecraft.network.protocol.common.ServerboundCustomClickActionPacket;
import net.minecraft.resources.Identifier;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.dialog.ActionButton;
import net.minecraft.server.dialog.CommonButtonData;
import net.minecraft.server.dialog.CommonDialogData;
import net.minecraft.server.dialog.ConfirmationDialog;
import net.minecraft.server.dialog.DialogAction;
import net.minecraft.server.dialog.Input;
import net.minecraft.server.dialog.action.CustomAll;
import net.minecraft.server.dialog.body.PlainMessage;
import net.minecraft.server.dialog.input.TextInput;
import net.minecraft.server.network.ConfigurationTask;
import net.minecraft.server.network.ServerConfigurationPacketListenerImpl;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;

/**
 * The server's one password, asked for before a player gets past logging in, so anyone without it gets no world, no
 * resource pack and no chat, and the agent never hears of them. It's Minecraft's own dialog, so nothing is needed on
 * the client. Getting it right is remembered per account until the password changes, which is also what stops a
 * restart behind the proxy from asking again.
 *
 * Only a salted hash is mounted in here, because agent-written code runs in this process too. With no hash there's no
 * gate, which is how the shadow server and local test stacks run.
 */
public final class PasswordGate {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path HASH = Path.of("/run/secrets/game_password");
	private static final Path APPROVED = Path.of("config", "conduit", "password_approved.txt");
	private static final Identifier ENTER = Identifier.fromNamespaceAndPath(Conduit.MOD_ID, "password_enter");
	private static final Identifier LEAVE = Identifier.fromNamespaceAndPath(Conduit.MOD_ID, "password_leave");
	private static final String FIELD = "password";
	private static final int LONGEST = 128;
	private static final int BOX_WIDTH = 200;
	private static final int BUTTON_WIDTH = 120;
	private static final int TRIES_PER_CONNECTION = 3;
	private static final int TRIES_PER_HOUR = 10;
	private static final long HOUR_MILLIS = 3_600_000;
	private static final int TICKS_TO_ANSWER = 5 * 60 * 20;
	private static final String ASK = "This server has a password. It's the same one as the website.";
	private static final String TRY_AGAIN = "That's not the password. Try again.";
	private static final String TOO_MANY = "Too many wrong passwords. Try again later.";
	private static final String TOO_SLOW = "Nobody entered the password, so you were disconnected.";

	private static final Map<ServerConfigurationPacketListenerImpl, Asking> ASKING = new ConcurrentHashMap<>();
	private static final Map<UUID, List<Long>> WRONG = new ConcurrentHashMap<>();

	private PasswordGate() {}

	public static void register() {
		LOGGER.info(stored() == null ? "password gate off: anyone who can log in can join" : "password gate on");
		// Before Minecraft's own configuration begins, so this comes ahead of the resource pack and everything else.
		ServerConfigurationConnectionEvents.BEFORE_CONFIGURE.register((handler, server) -> {
			String stored = stored();
			UUID player = handler.getOwner().id();
			if (stored == null || approved(stored).contains(player.toString())) {
				return;
			}
			if (recentlyWrong(player) >= TRIES_PER_HOUR) {
				handler.disconnect(Component.literal(TOO_MANY));
				return;
			}
			handler.addTask(new Asking(handler, server, stored));
		});
		ServerConfigurationConnectionEvents.DISCONNECT.register((handler, server) -> ASKING.remove(handler));
	}

	/** Called on the server thread with a button press from a dialog. True if it was one of this gate's own. */
	public static boolean answer(ServerConfigurationPacketListenerImpl handler, ServerboundCustomClickActionPacket packet) {
		if (LEAVE.equals(packet.id())) {
			handler.disconnect(Component.literal("See you."));
			return true;
		}
		if (!ENTER.equals(packet.id())) {
			return false;
		}
		Asking asking = ASKING.get(handler);
		if (asking == null || asking.checking) {
			return true;
		}
		asking.checking = true;
		String attempt = packet.payload().flatMap(Tag::asCompound).flatMap(tag -> tag.getString(FIELD)).orElse("").strip();
		// The hash is slow on purpose, so it can't run on the server thread.
		Thread.ofVirtual().name("conduit-password").start(() -> {
			boolean right = matches(asking.stored, attempt);
			asking.server.execute(() -> asking.finish(right));
		});
		return true;
	}

	private static String stored() {
		try {
			String text = Files.exists(HASH) ? Files.readString(HASH).strip() : "";
			return text.isEmpty() ? null : text;
		} catch (IOException error) {
			// Can't tell, so this counts as having a password that nobody can match, rather than as having none.
			LOGGER.error("Can't read the password's hash", error);
			return "unreadable";
		}
	}

	/** The stored form is pbkdf2_sha256$rounds$salt$hash, written by scripts/password_hash.py. */
	private static boolean matches(String stored, String attempt) {
		try {
			String[] parts = stored.split("\\$");
			byte[] salt = Base64.getDecoder().decode(parts[2]);
			byte[] expected = Base64.getDecoder().decode(parts[3]);
			PBEKeySpec spec = new PBEKeySpec(attempt.toCharArray(), salt, Integer.parseInt(parts[1]), expected.length * 8);
			byte[] actual = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();
			return MessageDigest.isEqual(actual, expected);
		} catch (GeneralSecurityException | RuntimeException error) {
			LOGGER.error("Can't check the password: {}", error.getClass().getSimpleName());
			return false;
		}
	}

	private static Set<String> approved(String stored) {
		try {
			List<String> lines = Files.exists(APPROVED) ? Files.readAllLines(APPROVED) : List.of();
			// The first line says which password these players passed. A new one has a new salt, so nobody has passed it yet.
			if (!lines.isEmpty() && lines.getFirst().equals(stored)) {
				return new LinkedHashSet<>(lines.subList(1, lines.size()));
			}
		} catch (IOException error) {
			LOGGER.error("Can't read who has passed the password", error);
		}
		return new LinkedHashSet<>();
	}

	private static void approve(UUID player, String stored) {
		Set<String> players = approved(stored);
		players.add(player.toString());
		List<String> lines = new ArrayList<>();
		lines.add(stored);
		lines.addAll(players);
		try {
			Files.createDirectories(APPROVED.getParent());
			Files.write(APPROVED, lines);
		} catch (IOException error) {
			LOGGER.error("Can't record who has passed the password", error);
		}
	}

	private static int recentlyWrong(UUID player) {
		List<Long> times = WRONG.get(player);
		if (times == null) {
			return 0;
		}
		times.removeIf(time -> System.currentTimeMillis() - time > HOUR_MILLIS);
		return times.size();
	}

	private static Packet<?> dialog(String message) {
		CommonDialogData common = new CommonDialogData(Component.literal("Living Mod"), Optional.empty(), false, false, DialogAction.CLOSE,
				List.of(new PlainMessage(Component.literal(message), BOX_WIDTH)),
				List.of(new Input(FIELD, new TextInput(BOX_WIDTH, Component.literal("Password"), true, "", LONGEST, Optional.empty()))));
		ActionButton enter = new ActionButton(new CommonButtonData(Component.literal("Enter"), BUTTON_WIDTH), Optional.of(new CustomAll(ENTER, Optional.empty())));
		ActionButton leave = new ActionButton(new CommonButtonData(Component.literal("Leave"), BUTTON_WIDTH), Optional.of(new CustomAll(LEAVE, Optional.empty())));
		return new ClientboundShowDialogPacket(Holder.direct(new ConfirmationDialog(common, enter, leave)));
	}

	private static final class Asking implements ConfigurationTask {
		private static final Type TYPE = new Type("conduit:password");

		private final ServerConfigurationPacketListenerImpl handler;
		private final MinecraftServer server;
		private final String stored;
		private boolean checking;
		private int wrongHere;
		private int ticks;

		private Asking(ServerConfigurationPacketListenerImpl handler, MinecraftServer server, String stored) {
			this.handler = handler;
			this.server = server;
			this.stored = stored;
		}

		@Override
		public void start(Consumer<Packet<?>> sender) {
			ASKING.put(this.handler, this);
			sender.accept(dialog(ASK));
		}

		@Override
		public boolean tick() {
			if (++this.ticks > TICKS_TO_ANSWER) {
				this.handler.disconnect(Component.literal(TOO_SLOW));
			}
			return false;
		}

		@Override
		public Type type() {
			return TYPE;
		}

		private void finish(boolean right) {
			this.checking = false;
			if (!ASKING.containsKey(this.handler)) {
				return;
			}
			UUID player = this.handler.getOwner().id();
			String name = this.handler.getOwner().name();
			if (right) {
				ASKING.remove(this.handler);
				approve(player, this.stored);
				LOGGER.info("{} entered the password", name);
				this.handler.completeTask(TYPE);
				return;
			}
			LOGGER.warn("{} got the password wrong", name);
			WRONG.computeIfAbsent(player, id -> new ArrayList<>()).add(System.currentTimeMillis());
			if (++this.wrongHere >= TRIES_PER_CONNECTION || recentlyWrong(player) >= TRIES_PER_HOUR) {
				this.handler.disconnect(Component.literal(TOO_MANY));
			} else {
				this.handler.send(dialog(TRY_AGAIN));
			}
		}
	}
}
