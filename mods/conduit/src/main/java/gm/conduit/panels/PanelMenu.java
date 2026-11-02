package gm.conduit.panels;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import gm.conduit.api.PanelBehavior;
import gm.conduit.api.PanelRow;
import gm.conduit.api.PanelView;
import gm.conduit.pack.Words;
import gm.conduit.slots.SlotBlockEntity;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.util.StringUtil;
import net.minecraft.world.Container;
import net.minecraft.world.SimpleContainer;
import net.minecraft.world.SimpleMenuProvider;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ContainerInput;
import net.minecraft.world.inventory.MenuType;
import net.minecraft.world.inventory.Slot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.component.ItemLore;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Consumer;
import java.util.function.Predicate;

/**
 * A panel on the server, which is a real chest menu whatever a player's client makes of it. Item slots are real slots, so moving
 * things, hoppers and what's safe all work as usual, and the rest of the chest holds a picture of each thing that can be read or
 * clicked. A companion that knows about panels draws its own screen for the same menu, and its clicks on a button are clicks on that
 * picture, so a client with no companion gets a plain chest that does all the same things, and there's only one way in.
 */
public final class PanelMenu extends AbstractContainerMenu implements PanelView {
	private static final List<MenuType<?>> BY_ROWS = List.of(MenuType.GENERIC_9x1, MenuType.GENERIC_9x2, MenuType.GENERIC_9x3,
			MenuType.GENERIC_9x4, MenuType.GENERIC_9x5, MenuType.GENERIC_9x6);
	private static final int ROW = 9;
	private static final int RIGHT_BUTTON = 1;
	private static final int MOST_TYPED_PER_SECOND = 20;
	private static final int TICKS_PER_SECOND = 20;
	private static final int PERCENT = 100;
	private static final int PAGE_BUTTONS = 2;

	private final ServerPlayer player;
	private final PanelDefinition definition;
	private final PanelBehavior behavior;
	private final Consumer<Runnable> guard;
	private final Predicate<Player> stillThere;
	private final Container container;
	private final boolean ownContainer;
	private final SimpleContainer pictures;
	private final int chestSize;
	private final Map<String, String> texts = new HashMap<>();
	private final Map<String, String> tooltips = new HashMap<>();
	private final Map<String, String> typed = new HashMap<>();
	private final Map<String, Float> values = new HashMap<>();
	private final Map<String, Boolean> enabled = new HashMap<>();
	private final Map<String, Boolean> visible = new HashMap<>();
	private final Map<String, ItemStack> items = new HashMap<>();
	private final Map<String, List<PanelRow>> rows = new HashMap<>();
	// Which page of a long list a plain chest is showing.
	private final Map<String, Integer> listPages = new HashMap<>();
	private String page = "";
	private JsonObject pending = new JsonObject();
	private List<ItemStack> pendingStacks = new ArrayList<>();
	private int lastTick = -1;
	private int typedThisSecond;
	private int secondStarted;

	/**
	 * @param given what its item slots show, or null for an inventory of its own
	 * @param stillThere whether this player can still be using it, which closes it the moment they can't
	 * @param guard runs a module's code, so one that keeps failing gets switched off the same as anywhere else
	 */
	public PanelMenu(int id, Inventory inventory, ServerPlayer player, PanelDefinition definition, Container given, Predicate<Player> stillThere, PanelBehavior behavior, Consumer<Runnable> guard) {
		super(BY_ROWS.get(definition.chestRows() - 1), id);
		this.player = player;
		this.definition = definition;
		this.behavior = behavior;
		this.guard = guard;
		this.stillThere = stillThere;
		this.ownContainer = given == null;
		this.container = given != null ? given : new SimpleContainer(definition.chestRows() * ROW);
		this.chestSize = definition.chestRows() * ROW;
		this.pictures = new SimpleContainer(this.chestSize);
		for (PanelDefinition.Widget widget : definition.widgets()) {
			if (widget.type().equals("slot") && widget.containerSlot() >= this.container.getContainerSize()) {
				throw new IllegalArgumentException("Panel " + definition.name() + " shows slot " + widget.containerSlot() + " of something with only " + this.container.getContainerSize());
			}
		}
		for (int slot = 0; slot < this.chestSize; slot++) {
			PanelDefinition.Widget widget = definition.byChestSlot().get(slot);
			addSlot(widget != null && widget.type().equals("slot") ? new Real(this.container, widget) : new Picture(this.pictures, slot));
		}
		addStandardInventorySlots(inventory, 0, 0);
		for (PanelDefinition.Widget widget : definition.widgets()) {
			if (widget.type().equals("tabs") && !widget.tabs().isEmpty() && this.page.isEmpty()) {
				this.page = widget.tabs().getFirst().id();
			}
		}
		pending.addProperty("page", this.page);
		for (PanelDefinition.Widget widget : definition.widgets()) {
			if (widget.startsHidden()) {
				setVisible(widget.id(), false);
			}
		}
		guard.accept(() -> behavior.opened(this));
		drawPictures();
		sendOpening();
	}

	/** How a panel looks when nothing is driving it, which is what a builder and a reviewer see of it before it goes out. */
	public static void preview(ServerPlayer player, String name) {
		PanelDefinition definition = PanelDefinition.find("", name, player);
		player.openMenu(new SimpleMenuProvider((id, inventory, who) -> new PanelMenu(id, inventory, player, definition, null, anyone -> true, new PanelBehavior() {}, Runnable::run),
				Component.literal(definition.title())));
	}

	/** A slot on a tab that isn't showing can't be used, even by a client that's been told otherwise. */
	private final class Real extends Slot {
		private final PanelDefinition.Widget widget;

		Real(Container container, PanelDefinition.Widget widget) {
			super(container, widget.containerSlot(), 0, 0);
			this.widget = widget;
		}

		@Override
		public boolean mayPlace(ItemStack stack) {
			return isShown(this.widget) && this.container.canPlaceItem(getContainerSlot(), stack);
		}

		@Override
		public int getMaxStackSize() {
			return this.container instanceof SlotBlockEntity machine ? machine.limitOf(getContainerSlot()) : super.getMaxStackSize();
		}

		@Override
		public void onTake(Player player, ItemStack stack) {
			super.onTake(player, stack);
			if (this.container instanceof SlotBlockEntity machine) {
				machine.taken(getContainerSlot(), stack, player);
			}
		}

		@Override
		public boolean mayPickup(Player player) {
			return isShown(this.widget) && (!(this.container instanceof SlotBlockEntity machine) || machine.mayTake(getContainerSlot(), player));
		}
	}

	private static final class Picture extends Slot {
		Picture(Container container, int slot) {
			super(container, slot, 0, 0);
		}

		@Override
		public boolean mayPlace(ItemStack stack) {
			return false;
		}

		@Override
		public boolean mayPickup(Player player) {
			return false;
		}
	}

	private boolean isShown(PanelDefinition.Widget widget) {
		return this.visible.getOrDefault(widget.id(), true) && (widget.page().isEmpty() || widget.page().equals(this.page));
	}

	private boolean isEnabled(PanelDefinition.Widget widget) {
		return this.enabled.getOrDefault(widget.id(), widget.enabled());
	}

	@Override
	public void clicked(int slot, int button, ContainerInput input, Player clicker) {
		PanelDefinition.Widget widget = this.definition.byChestSlot().get(slot);
		if (slot < 0 || slot >= this.chestSize || widget != null && widget.type().equals("slot")) {
			super.clicked(slot, button, input, clicker);
			return;
		}
		// Only a press counts, so a drag or a double click isn't taken for several presses.
		if (widget != null && (input == ContainerInput.PICKUP || input == ContainerInput.QUICK_MOVE) && isShown(widget)) {
			press(widget, slot - widget.chestSlot(), button == RIGHT_BUTTON, input == ContainerInput.QUICK_MOVE);
		}
		// The client has already moved the picture in its own mind, so it has to be told again.
		sendAllDataToRemote();
	}

	private void press(PanelDefinition.Widget widget, int offset, boolean rightClick, boolean shift) {
		switch (widget.type()) {
			case "button" -> {
				if (isEnabled(widget)) {
					this.guard.accept(() -> this.behavior.clicked(this, widget.id(), 0, rightClick, shift));
				}
			}
			case "tabs" -> {
				String tab = widget.tabs().get(offset).id();
				setPage(tab);
				this.guard.accept(() -> this.behavior.clicked(this, tab, 0, rightClick, shift));
			}
			case "list" -> {
				if (isPageButton(widget, offset)) {
					this.listPages.put(widget.id(), pageOf(widget) + (offset == rowsAPage(widget) ? -1 : 1));
				} else {
					pressRow(widget, firstRowShown(widget) + offset, rightClick, shift);
				}
			}
			case "filter" -> {
				if (isEnabled(widget)) {
					// One of whatever they're holding, or nothing with an empty hand, and either way they keep it.
					ItemStack chosen = getCarried().copyWithCount(getCarried().isEmpty() ? 0 : 1);
					setFilter(widget.id(), chosen);
					this.guard.accept(() -> this.behavior.filtered(this, widget.id(), chosen));
				}
			}
			default -> {}
		}
		drawPictures();
		flush();
	}

	private void pressRow(PanelDefinition.Widget widget, int row, boolean rightClick, boolean shift) {
		List<PanelRow> list = this.rows.getOrDefault(widget.id(), List.of());
		if (row >= 0 && row < list.size() && list.get(row).enabled()) {
			this.guard.accept(() -> this.behavior.clicked(this, widget.id(), row, rightClick, shift));
		}
	}

	/** Only for a list too long to have a place in the chest for each row, and only what could have been clicked anyway. */
	void rowClickedByClient(String id, int row, boolean rightClick, boolean shift) {
		PanelDefinition.Widget widget = this.definition.byId().get(id);
		if (widget == null || !widget.paged() || !isShown(widget) || !stillValid(this.player)) {
			return;
		}
		pressRow(widget, row, rightClick, shift);
		drawPictures();
		flush();
	}

	private static int rowsAPage(PanelDefinition.Widget widget) {
		return widget.paged() ? widget.size() - PAGE_BUTTONS : widget.size();
	}

	private static boolean isPageButton(PanelDefinition.Widget widget, int offset) {
		return widget.paged() && offset >= rowsAPage(widget);
	}

	private int pageOf(PanelDefinition.Widget widget) {
		int last = Math.max(0, (this.rows.getOrDefault(widget.id(), List.of()).size() - 1) / rowsAPage(widget));
		return Math.clamp(this.listPages.getOrDefault(widget.id(), 0), 0, last);
	}

	private int firstRowShown(PanelDefinition.Widget widget) {
		return pageOf(widget) * rowsAPage(widget);
	}

	/** What came from a client is only an id and some text, and it's only used if this panel has that field, and it can be typed in right now. */
	void typedByClient(String id, String value) {
		PanelDefinition.Widget widget = this.definition.byId().get(id);
		if (widget == null || !widget.type().equals("text_field") || !isShown(widget) || !isEnabled(widget) || !stillValid(this.player)) {
			return;
		}
		int second = this.player.tickCount / TICKS_PER_SECOND;
		if (second != this.secondStarted) {
			this.secondStarted = second;
			this.typedThisSecond = 0;
		}
		if (++this.typedThisSecond > MOST_TYPED_PER_SECOND) {
			return;
		}
		String clean = StringUtil.filterText(value);
		String kept = clean.length() > widget.maxLength() ? clean.substring(0, widget.maxLength()) : clean;
		if (!kept.equals(this.typed.get(id))) {
			this.typed.put(id, kept);
			this.guard.accept(() -> this.behavior.typed(this, id, kept));
		}
	}

	@Override
	public ItemStack quickMoveStack(Player mover, int index) {
		Slot slot = this.slots.get(index);
		if (!slot.hasItem() || !slot.mayPickup(mover)) {
			return ItemStack.EMPTY;
		}
		ItemStack stack = slot.getItem();
		ItemStack before = stack.copy();
		boolean moved = false;
		if (index < this.chestSize) {
			moved = moveItemStackTo(stack, this.chestSize, this.slots.size(), true);
		} else {
			// One at a time, because the game adds to anything holding the same item, and that would be a picture, or a machine's output.
			for (int place = 0; place < this.chestSize && !stack.isEmpty(); place++) {
				if (this.slots.get(place) instanceof Real real && real.mayPlace(stack)) {
					moved |= moveItemStackTo(stack, place, place + 1, false);
				}
			}
		}
		if (!moved) {
			return ItemStack.EMPTY;
		}
		// A slot can hand back what it's given, like one that only remembers which item to filter, and it can land right back here. Then nothing
		// moved overall, and the game asks again for as long as this says something did, which would hang the whole server.
		ItemStack now = slot.getItem();
		if (ItemStack.isSameItemSameComponents(now, before) && now.getCount() >= before.getCount()) {
			slot.setChanged();
			return ItemStack.EMPTY;
		}
		if (index < this.chestSize) {
			slot.onTake(mover, before.copyWithCount(before.getCount() - stack.getCount()));
		}
		if (now.isEmpty()) {
			slot.setByPlayer(ItemStack.EMPTY);
		} else {
			slot.setChanged();
		}
		return before;
	}

	@Override
	public boolean stillValid(Player who) {
		return this.stillThere.test(who);
	}

	/** The game calls this every tick for whatever a player has open, and sometimes more. */
	@Override
	public void broadcastChanges() {
		if (this.player.tickCount != this.lastTick) {
			this.lastTick = this.player.tickCount;
			this.guard.accept(() -> this.behavior.tick(this));
			drawPictures();
			flush();
		}
		super.broadcastChanges();
	}

	@Override
	public void removed(Player who) {
		super.removed(who);
		if (this.ownContainer) {
			clearContainer(who, this.container);
		}
		this.guard.accept(() -> this.behavior.closed(this));
	}

	private void sendOpening() {
		if (!PanelNetwork.canDraw(this.player, this.definition)) {
			clearPending();
			return;
		}
		JsonObject icons = new JsonObject();
		for (PanelDefinition.Widget widget : this.definition.widgets()) {
			addIcon(icons, widget.icon());
			widget.tabs().forEach(tab -> addIcon(icons, tab.icon()));
		}
		this.pending.add("icons", icons);
		PanelNetwork.send(this.player, new PanelNetwork.Shown(this.containerId, this.definition.text(), this.pending.toString(), this.pendingStacks));
		clearPending();
	}

	private void addIcon(JsonObject icons, String item) {
		if (!item.isEmpty() && !icons.has(item)) {
			icons.addProperty(item, this.pendingStacks.size());
			this.pendingStacks.add(stackOf(item));
		}
	}

	private void flush() {
		if (this.pending.isEmpty()) {
			return;
		}
		if (PanelNetwork.canDraw(this.player, this.definition)) {
			PanelNetwork.send(this.player, new PanelNetwork.Shown(this.containerId, "", this.pending.toString(), this.pendingStacks));
		}
		clearPending();
	}

	private void clearPending() {
		this.pending = new JsonObject();
		this.pendingStacks = new ArrayList<>();
	}

	private JsonObject pendingOf(String kind) {
		if (!this.pending.has(kind)) {
			this.pending.add(kind, new JsonObject());
		}
		return this.pending.getAsJsonObject(kind);
	}

	private PanelDefinition.Widget widget(String id) {
		PanelDefinition.Widget found = this.definition.byId().get(id);
		if (found == null) {
			throw new IllegalArgumentException("Panel " + this.definition.name() + " has no widget called " + id);
		}
		return found;
	}

	private static ItemStack stackOf(String item) {
		return new ItemStack(BuiltInRegistries.ITEM.getValue(Identifier.parse(item)));
	}

	// What a plain chest shows ------------------------------------------------------------------------------

	private void drawPictures() {
		for (PanelDefinition.Widget widget : this.definition.widgets()) {
			if (widget.chestSlot() < 0 || widget.type().equals("slot")) {
				continue;
			}
			for (int offset = 0; offset < widget.size(); offset++) {
				ItemStack picture = isShown(widget) ? picture(widget, offset) : ItemStack.EMPTY;
				if (!ItemStack.matches(this.pictures.getItem(widget.chestSlot() + offset), picture)) {
					this.pictures.setItem(widget.chestSlot() + offset, picture);
				}
			}
		}
	}

	private ItemStack picture(PanelDefinition.Widget widget, int offset) {
		String text = this.texts.getOrDefault(widget.id(), widget.text());
		String tooltip = this.tooltips.getOrDefault(widget.id(), widget.tooltip());
		return switch (widget.type()) {
			case "tabs" -> {
				PanelDefinition.Tab tab = widget.tabs().get(offset);
				if (tab.icon().isEmpty()) {
					yield named(new ItemStack(tab.id().equals(this.page) ? Items.EMERALD : Items.PAPER), tab.text(), "");
				}
				ItemStack shown = named(stackOf(tab.icon()), tab.text(), "");
				if (tab.id().equals(this.page)) {
					shown.set(DataComponents.ENCHANTMENT_GLINT_OVERRIDE, true);
				}
				yield shown;
			}
			case "list" -> {
				List<PanelRow> list = this.rows.getOrDefault(widget.id(), List.of());
				if (isPageButton(widget, offset)) {
					yield pageButton(widget, offset == rowsAPage(widget));
				}
				int index = firstRowShown(widget) + offset;
				if (index >= list.size()) {
					yield ItemStack.EMPTY;
				}
				yield rowPicture(list.get(index));
			}
			case "filter" -> {
				ItemStack chosen = this.items.getOrDefault(widget.id(), ItemStack.EMPTY);
				yield named(chosen.isEmpty() ? new ItemStack(Items.ITEM_FRAME) : chosen.copyWithCount(1), text, chosen.isEmpty() ? Words.shown(this.player, "conduit.panel.filter_empty", "Click with an item to choose it.") : tooltip);
			}
			case "bar" -> named(new ItemStack(Items.CLOCK), text + " " + Math.round(this.values.getOrDefault(widget.id(), widget.value()) * PERCENT) + "%", tooltip);
			case "text_field" -> named(new ItemStack(Items.NAME_TAG), text, Words.shown(this.player, "conduit.panel.needs_companion", "Typing here needs the companion mod."));
			case "icon" -> named(this.items.containsKey(widget.id()) ? this.items.get(widget.id()).copyWithCount(1) : stackOf(widget.icon()), text, tooltip);
			default -> {
				ItemStack base = widget.icon().isEmpty() ? new ItemStack(Items.PAPER) : stackOf(widget.icon());
				yield named(base, isEnabled(widget) ? text : notAvailable(text), tooltip);
			}
		};
	}

	private ItemStack rowPicture(PanelRow row) {
		ItemStack stack = row.icon().isEmpty() ? new ItemStack(Items.PAPER) : row.icon().copyWithCount(1);
		named(stack, row.enabled() ? row.text() : notAvailable(row.text()), "");
		// What the companion draws beside the row has to go somewhere in a plain chest, and this is where a tooltip goes.
		List<Component> lines = new ArrayList<>();
		if (!row.detail().isEmpty()) {
			lines.add(Component.literal(row.detail()));
		}
		for (ItemStack extra : row.icons()) {
			lines.add(Component.literal(extra.getCount() + " ").append(extra.getHoverName()));
		}
		if (!row.tooltip().isEmpty()) {
			lines.add(Component.literal(row.tooltip()));
		}
		if (!lines.isEmpty()) {
			stack.set(DataComponents.LORE, new ItemLore(lines));
		}
		return stack;
	}

	private ItemStack pageButton(PanelDefinition.Widget widget, boolean back) {
		int pages = (this.rows.getOrDefault(widget.id(), List.of()).size() - 1) / rowsAPage(widget) + 1;
		String name = back ? Words.shown(this.player, "conduit.panel.page_back", "Previous page") : Words.shown(this.player, "conduit.panel.page_on", "Next page");
		return named(new ItemStack(back ? Items.ARROW : Items.SPECTRAL_ARROW), name, (pageOf(widget) + 1) + " / " + Math.max(1, pages));
	}

	private String notAvailable(String text) {
		return Words.shown(this.player, "conduit.panel.not_available", "%s (not available)", text);
	}

	private static ItemStack named(ItemStack stack, String name, String tooltip) {
		if (!name.isEmpty()) {
			stack.set(DataComponents.CUSTOM_NAME, Component.literal(name));
		}
		if (!tooltip.isEmpty()) {
			stack.set(DataComponents.LORE, new ItemLore(List.of(Component.literal(tooltip))));
		}
		return stack;
	}

	// What a module can do ----------------------------------------------------------------------------------

	@Override
	public ServerPlayer player() {
		return this.player;
	}

	@Override
	public Container container() {
		return this.container;
	}

	@Override
	public void setText(String id, String text) {
		widget(id);
		if (!text.equals(this.texts.put(id, text))) {
			pendingOf("text").addProperty(id, text);
		}
	}

	@Override
	public void setValue(String id, float value) {
		widget(id);
		float kept = Math.clamp(value, 0.0F, 1.0F);
		Float before = this.values.put(id, kept);
		if (before == null || before != kept) {
			pendingOf("value").addProperty(id, kept);
		}
	}

	@Override
	public void setEnabled(String id, boolean on) {
		widget(id);
		if (!Objects.equals(this.enabled.put(id, on), on)) {
			pendingOf("enabled").addProperty(id, on);
		}
	}

	@Override
	public void setVisible(String id, boolean on) {
		widget(id);
		if (!Objects.equals(this.visible.put(id, on), on)) {
			pendingOf("visible").addProperty(id, on);
		}
	}

	@Override
	public void setTooltip(String id, String tooltip) {
		widget(id);
		if (!tooltip.equals(this.tooltips.put(id, tooltip))) {
			pendingOf("tooltip").addProperty(id, tooltip);
		}
	}

	@Override
	public void setItem(String id, ItemStack stack) {
		widget(id);
		ItemStack before = this.items.put(id, stack.copy());
		if (before == null || !ItemStack.matches(before, stack)) {
			pendingOf("items").addProperty(id, this.pendingStacks.size());
			this.pendingStacks.add(stack.copy());
		}
	}

	@Override
	public void setRows(String id, List<PanelRow> rows) {
		PanelDefinition.Widget widget = widget(id);
		List<PanelRow> kept = List.copyOf(rows.subList(0, Math.min(rows.size(), widget.mostRows())));
		List<PanelRow> before = this.rows.put(id, kept);
		if (before != null && sameRows(before, kept)) {
			return;
		}
		JsonArray list = new JsonArray();
		for (PanelRow row : kept) {
			JsonObject raw = new JsonObject();
			raw.addProperty("text", row.text());
			raw.addProperty("enabled", row.enabled());
			raw.addProperty("tooltip", row.tooltip());
			if (!row.detail().isEmpty()) {
				raw.addProperty("detail", row.detail());
			}
			if (!row.icon().isEmpty()) {
				raw.addProperty("icon", this.pendingStacks.size());
				this.pendingStacks.add(row.icon().copy());
			}
			if (!row.icons().isEmpty()) {
				JsonArray more = new JsonArray();
				for (ItemStack extra : row.icons()) {
					more.add(this.pendingStacks.size());
					this.pendingStacks.add(extra.copy());
				}
				raw.add("icons", more);
			}
			list.add(raw);
		}
		if (!this.pending.has("rows")) {
			this.pending.add("rows", new JsonObject());
		}
		this.pending.getAsJsonObject("rows").add(id, list);
	}

	private static boolean sameRows(List<PanelRow> first, List<PanelRow> second) {
		if (first.size() != second.size()) {
			return false;
		}
		for (int index = 0; index < first.size(); index++) {
			PanelRow a = first.get(index);
			PanelRow b = second.get(index);
			if (!a.text().equals(b.text()) || a.enabled() != b.enabled() || !a.tooltip().equals(b.tooltip()) || !a.detail().equals(b.detail())
					|| !ItemStack.matches(a.icon(), b.icon()) || !ItemStack.listMatches(a.icons(), b.icons())) {
				return false;
			}
		}
		return true;
	}

	@Override
	public void setFilter(String id, ItemStack stack) {
		setItem(id, stack);
	}

	@Override
	public ItemStack filter(String id) {
		widget(id);
		return this.items.getOrDefault(id, ItemStack.EMPTY).copy();
	}

	@Override
	public void setTyped(String id, String value) {
		widget(id);
		if (!value.equals(this.typed.put(id, value))) {
			pendingOf("typed").addProperty(id, value);
		}
	}

	@Override
	public String typed(String id) {
		widget(id);
		return this.typed.getOrDefault(id, "");
	}

	@Override
	public void setPage(String next) {
		if (!next.equals(this.page)) {
			this.page = next;
			this.pending.addProperty("page", next);
		}
	}

	@Override
	public String page() {
		return this.page;
	}

	@Override
	public void close() {
		this.player.closeContainer();
	}
}
