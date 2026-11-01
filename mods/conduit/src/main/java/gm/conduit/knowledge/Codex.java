package gm.conduit.knowledge;

import com.mojang.brigadier.Command;
import com.mojang.brigadier.arguments.StringArgumentType;
import gm.conduit.pack.Words;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.ChatFormatting;
import net.minecraft.commands.Commands;
import net.minecraft.core.component.DataComponents;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.network.protocol.game.ClientboundOpenBookPacket;
import net.minecraft.network.protocol.game.ClientboundSetPlayerInventoryPacket;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.Filterable;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.component.WrittenBookContent;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * The book that holds what a player has learned. With the companion and Patchouli, it's a real book with categories and a search, whose
 * pages come in the resource pack (broker/guide.py), and all this does is say which of them this player has earned and when to open it.
 * The companion's Guide must stay in step with the format.
 *
 * <p>Anyone else gets it as a written book. That's never a real item: the client is told briefly that it's holding a book, which opens
 * the screen, and is then told the truth. So it can't be dropped, copied or lost, and it needs no client changes.
 */
public final class Codex {
	private static final int PAGE_CHARACTERS = 230;
	private static final int CHECK_TICKS = 100;
	private static final Map<UUID, Set<String>> SENT = new HashMap<>();

	private Codex() {}

	public static void register() {
		PayloadTypeRegistry.clientboundPlay().register(Flags.TYPE, Flags.CODEC);
		PayloadTypeRegistry.clientboundPlay().register(Open.TYPE, Open.CODEC);
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
				Commands.literal("codex")
						.executes(context -> {
							open(context.getSource().getPlayerOrException());
							return Command.SINGLE_SUCCESS;
						})
						.then(Commands.argument("entry", StringArgumentType.word()).executes(context -> {
							open(context.getSource().getPlayerOrException(), StringArgumentType.getString(context, "entry"));
							return Command.SINGLE_SUCCESS;
						}))));
		ServerTickEvents.END_SERVER_TICK.register(server -> {
			if (server.getTickCount() % CHECK_TICKS == 0) {
				server.getPlayerList().getPlayers().forEach(Codex::sendIfChanged);
			}
		});
		ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> sendIfChanged(handler.player));
		ServerPlayConnectionEvents.DISCONNECT.register((handler, server) -> SENT.remove(handler.player.getUUID()));
		// A release can add entries, which their book has to hear about even if it knows nothing more than before.
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> SENT.clear());
	}

	public static void open(ServerPlayer player) {
		open(player, "");
	}

	/** Opens at one entry, if it's one they know, and otherwise at the start. */
	public static void open(ServerPlayer player, String entry) {
		List<KnowledgePlan.Entry> known = Knowledge.instance().knownEntries(player);
		if (known.isEmpty()) {
			player.sendSystemMessage(Words.say("conduit.codex_empty", "§7Nothing is written here yet. Look closer at the world."));
			return;
		}
		if (ServerPlayNetworking.canSend(player, Open.TYPE)) {
			sendIfChanged(player);
			boolean earned = known.stream().anyMatch(item -> item.guide().equals(entry));
			ServerPlayNetworking.send(player, new Open(earned ? entry : ""));
			return;
		}
		List<Filterable<Component>> pages = new ArrayList<>();
		for (KnowledgePlan.Entry item : known) {
			// Pages hold so much text that where they end has to go by the words a player will really read, and it's only read once anyway.
			List<String> parts = split(Words.shown(player, item.titleKey() + ".text", item.text()));
			for (int index = 0; index < parts.size(); index++) {
				// A real style, because a §r here resets to white, which can't be read on a book's page.
				MutableComponent page = Component.empty();
				if (index == 0) {
					page.append(Component.literal(Words.shown(player, item.titleKey(), item.title())).withStyle(ChatFormatting.BOLD)).append("\n\n");
				}
				pages.add(Filterable.passThrough(page.append(parts.get(index))));
			}
		}
		showBook(player, Words.shown(player, "conduit.codex_title", "Codex"), pages);
	}

	private static void sendIfChanged(ServerPlayer player) {
		if (!ServerPlayNetworking.canSend(player, Flags.TYPE)) {
			return;
		}
		Set<String> known = Knowledge.instance().knownEntries(player).stream().map(KnowledgePlan.Entry::guide).filter(flag -> !flag.isEmpty()).collect(Collectors.toSet());
		if (known.equals(SENT.get(player.getUUID()))) {
			return;
		}
		SENT.put(player.getUUID(), known);
		List<String> unknown = Knowledge.instance().plan().entries().values().stream().map(KnowledgePlan.Entry::guide).filter(flag -> !flag.isEmpty() && !known.contains(flag)).toList();
		ServerPlayNetworking.send(player, new Flags(List.copyOf(known), unknown));
	}

	/** Opens a book for a player without any such book existing, which also works for what a module wants read. */
	public static void showBook(ServerPlayer player, String title, List<Filterable<Component>> pages) {
		ItemStack book = new ItemStack(Items.WRITTEN_BOOK);
		book.set(DataComponents.WRITTEN_BOOK_CONTENT, new WrittenBookContent(Filterable.passThrough(title), "", 0, pages, true));
		int slot = player.getInventory().getSelectedSlot();
		player.connection.send(new ClientboundSetPlayerInventoryPacket(slot, book));
		player.connection.send(new ClientboundOpenBookPacket(InteractionHand.MAIN_HAND));
		player.connection.send(new ClientboundSetPlayerInventoryPacket(slot, player.getInventory().getItem(slot)));
	}

	private static List<String> split(String text) {
		List<String> parts = new ArrayList<>();
		StringBuilder current = new StringBuilder();
		for (String word : text.split(" ")) {
			if (current.length() + word.length() + 1 > PAGE_CHARACTERS && !current.isEmpty()) {
				parts.add(current.toString());
				current.setLength(0);
			}
			if (!current.isEmpty()) {
				current.append(' ');
			}
			current.append(word);
		}
		if (!current.isEmpty()) {
			parts.add(current.toString());
		}
		return parts;
	}

	/** Which of the book's entries this player does and doesn't know, each by its flag. */
	private record Flags(List<String> known, List<String> unknown) implements CustomPacketPayload {
		static final Type<Flags> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "codex_flags"));
		static final StreamCodec<RegistryFriendlyByteBuf, Flags> CODEC = StreamCodec.composite(
				ByteBufCodecs.STRING_UTF8.apply(ByteBufCodecs.list()), Flags::known,
				ByteBufCodecs.STRING_UTF8.apply(ByteBufCodecs.list()), Flags::unknown,
				Flags::new);

		@Override
		public Type<Flags> type() {
			return TYPE;
		}
	}

	/** Opens the book, at an entry's flag or at the start if that's empty. */
	private record Open(String entry) implements CustomPacketPayload {
		static final Type<Open> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "codex_open"));
		static final StreamCodec<RegistryFriendlyByteBuf, Open> CODEC = StreamCodec.composite(ByteBufCodecs.STRING_UTF8, Open::entry, Open::new);

		@Override
		public Type<Open> type() {
			return TYPE;
		}
	}
}
