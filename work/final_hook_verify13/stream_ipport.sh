#!/bin/bash /etc/ikcommon
Include ipset.sh interface.sh iproute.sh lock.sh iptables.sh ipmacgroup.sh
Include route_rule.sh
LOCKUP="Lock stream_ipport"
UNLOCK="unLock stream_ipport"

STREAM_IPPORT_LANID=15000

INIT_CONFIG="/tmp/stream_ipport.iptables"
WG_STREAM_PREROUTE_RULE="/tmp/iktmp/ipt_rule_id/wg_stream_preroute_rule"
WG_STREAM_PREROUTE_CHAIN="WG_STREAM_PREROUTE"

boot()
{
	init
}

__wg_stream_cache_update()
{
	interface_get_name_to_cache_wan >/dev/null 2>&1 || true
	interface_get_name_to_cache_pptp >/dev/null 2>&1 || true
	interface_get_name_to_cache_l2tp >/dev/null 2>&1 || true
	interface_get_name_to_cache_ovpn >/dev/null 2>&1 || true
	interface_get_name_to_cache_iked >/dev/null 2>&1 || true
	interface_get_name_to_cache_wg >/dev/null 2>&1 || true
	__wg_stream_cache_append_running
}

__wg_stream_cache_append_one()
{
	local cache="$1" name="$2"
	[ "$cache" -a "$name" ] || return
	mkdir -p "$IK_DIR_CACHE/ifname" "$IK_DIR_CACHE/ifname_comment"
	touch "$IK_DIR_CACHE/ifname/$cache" "$IK_DIR_CACHE/ifname_comment/$cache"
	grep -qx "$name" "$IK_DIR_CACHE/ifname/$cache" 2>/dev/null || echo "$name" >> "$IK_DIR_CACHE/ifname/$cache"
	grep -q "^$name\\([[:space:]]\\|$\\)" "$IK_DIR_CACHE/ifname_comment/$cache" 2>/dev/null || echo "$name" >> "$IK_DIR_CACHE/ifname_comment/$cache"
}

__wg_stream_cache_append_running()
{
	local path name cache
	for path in /sys/class/net/*; do
		[ -e "$path" ] || continue
		name="${path##*/}"
		case "$name" in
			wg*) cache="wg" ;;
			ovpn*|tun[0-9]*|tap[0-9]*) cache="ovpn" ;;
			pptp*) cache="pptp" ;;
			l2tp*) cache="l2tp" ;;
			iked*|ipsec*) cache="iked" ;;
			ppp*) cache="pptp" ;;
			*) cache="" ;;
		esac
		[ "$cache" ] && __wg_stream_cache_append_one "$cache" "$name"
	done
}

__wg_stream_append_interface_json()
{
	local interface="$1"
	local wg_list
	local name
	local comment
	local item

	wg_list=$(
			{
				interface_get_ifname vpn 2>/dev/null | awk '{print $1"|"}'
				sqlite3 $IK_DB_CONFIG -separator "|" "select name,'' from wireguard where name like 'wg%' order by name" 2>/dev/null
				sqlite3 $IK_DB_CONFIG -separator "|" "select distinct interface,'' from wireguard_peers where interface like 'wg%' order by interface" 2>/dev/null
				for wg_if in /sys/class/net/wg* /sys/class/net/ovpn* /sys/class/net/tun[0-9]* /sys/class/net/tap[0-9]* /sys/class/net/pptp* /sys/class/net/l2tp* /sys/class/net/iked* /sys/class/net/ipsec* /sys/class/net/ppp*; do
					[ -e "$wg_if" ] && echo "${wg_if##*/}|"
				done
			} | awk -F'|' '$1!="" && !seen[$1]++'
		)

	while IFS='|' read name comment; do
		[ "$name" ] || continue
		echo "$interface" | grep -q "\"$name\"" && continue
		item="[\"$name\""
		[ "$comment" ] && item="$item,\"$comment\""
		item="$item]"
		if [ "$interface" = "" -o "$interface" = "[]" ]; then
			interface="[$item]"
		else
			interface="${interface%]},$item]"
		fi
	done <<EOF
$wg_list
EOF
	echo "${interface:-[]}"
}

__check_param()
{
	__wg_stream_cache_update
	check_varl \
		'enabled 	== "yes" or == "no"'\
		'type		== 0 or == 1' \
		'[ type == 0 ] && {
			interface ifnames_wan or ifnames_vpn ;
		}' \
		'[ type == 1 ] && {
			nexthop ip ;
		}' \
		'protocol 	== "any" or == "tcp" or == "udp" or == "tcp+udp" or == "icmp" ' \
		'src_port 	ports or == ""' \
		'dst_port 	ports or == ""' \
		'week		week' \
		'time		timeranges'
}

__check_interface_nums()
{
	local tmp_array=(${interface//,/ })
	local count=${#tmp_array[*]}
	if [ "$count" -gt "256" ]; then
		Autoiecho param ifaces_limit	
		return 1
	fi
	return 0
}

__wg_stream_iface_is_wan()
{
	local iface="$1"
	[ "$iface" ] || return 1
	echo "$iface" | grep -Eq '^(wan|vwan|adsl)'
}

__wg_stream_ensure_iface_route()
{
	local iface="$1"
	local mark_id="$2"
	[ "$iface" -a "$mark_id" ] || return

	ip rule show 2>/dev/null | grep -q "fwmark .*0x$(printf '%x' $mark_id).*lookup $iface" || \
		ip rule add from all fwmark $mark_id table $iface prio 15000 >/dev/null 2>&1

	if [ -e "/sys/class/net/$iface" ] && ! __wg_stream_iface_is_wan "$iface"; then
		ip route show table "$iface" 2>/dev/null | grep -q '^default ' || \
			ip route replace default dev "$iface" table "$iface" metric 100 >/dev/null 2>&1
	fi
}

__wg_stream_nat_comment()
{
	echo "wg-stream-nat:$1"
}

__wg_stream_ensure_nat()
{
	local iface="$1"
	[ "$iface" ] || return
	[ -e "/sys/class/net/$iface" ] || return
	__wg_stream_iface_is_wan "$iface" && return

	local comment=$(__wg_stream_nat_comment "$iface")
	iptables -w -t nat -S POSTROUTING 2>/dev/null | grep -q -- "$comment" || \
		iptables -w -t nat -A POSTROUTING -o "$iface" -m comment --comment "$comment" -j MASQUERADE >/dev/null 2>&1
}

__exec_rule_clean()
{
	> /tmp/iktmp/ipt_rule_id/stream_ipport_id_rule
	> "$WG_STREAM_PREROUTE_RULE"
}

__wg_stream_preroute_commit()
{
	iptables -w -t mangle -N "$WG_STREAM_PREROUTE_CHAIN" 2>/dev/null
	while iptables -w -t mangle -D PREROUTING -j "$WG_STREAM_PREROUTE_CHAIN" 2>/dev/null; do :; done
	iptables -w -t mangle -I PREROUTING 1 -j "$WG_STREAM_PREROUTE_CHAIN" 2>/dev/null
	iptables -w -t mangle -F "$WG_STREAM_PREROUTE_CHAIN" 2>/dev/null
	# Never policy-route WireGuard handshakes, router DNS, or other traffic
	# addressed to the router itself. Only forwarded client traffic belongs here.
	iptables -w -t mangle -A "$WG_STREAM_PREROUTE_CHAIN" -m addrtype --dst-type LOCAL -j RETURN 2>/dev/null

	[ -s "$WG_STREAM_PREROUTE_RULE" ] || return
	sort -n -k1 "$WG_STREAM_PREROUTE_RULE" |while read rule; do
		${rule#* } >/dev/null 2>&1
	done
}

__wg_stream_preroute_add_mark()
{
	local mark_id="$1"
	[ "$mark_id" ] || return
	echo $id iptables -w -t mangle -A "$WG_STREAM_PREROUTE_CHAIN" $src $dst $PROTO $sport $dport $COMMENT $ipt_time -m mark --mark 0 -j MARK --set-mark $mark_id >> "$WG_STREAM_PREROUTE_RULE"
	echo $id iptables -w -t mangle -A "$WG_STREAM_PREROUTE_CHAIN" $src $dst $PROTO $sport $dport $COMMENT $ipt_time -m mark ! --mark 0 -j CONNMARK --save-mark >> "$WG_STREAM_PREROUTE_RULE"
}

__exec_rule_commit()
{
	#重新排序规则
	iptables -w -t mangle -F STREAM_IPPORT_NEW

	> $INIT_CONFIG
	echo "*mangle" >> $INIT_CONFIG
	sort -n -k1 /tmp/iktmp/ipt_rule_id/stream_ipport_id_rule |while read rule;do
		echo "${rule//*-t mangle}" >> $INIT_CONFIG
	done
	echo "COMMIT" >> $INIT_CONFIG
	iptables-restore -n -T mangle $INIT_CONFIG >/dev/null 2>&1
	rm $INIT_CONFIG
	__wg_stream_preroute_commit
}

__exec_rule_add() {
	#封装规则变量
	local connmark_ids=
	local mark_ids=
	local PROTO

	local ipt_time=$(ipt_format_time "$week" "$time")
	COMMENT="-m comment --comment $id"
	IPTABLES_RULE_ALL="iptables -w -t mangle -A STREAM_IPPORT_ALL"
	IPTABLES_RULE_NEW="iptables -w -t mangle -A STREAM_IPPORT_NEW"

	if [ "$protocol" != "any"  ];then
		local PROTO="-p $protocol"
	fi

	if [ "$protocol" = "tcp+udp" -o "$protocol" = "tcp" -o "$protocol" = "udp" ];then
		[ -n "$src_port" ]&& sport="-m multiport --sports ${src_port//-/:}"
		[ -n "$dst_port" ]&& dport="-m multiport --dports ${dst_port//-/:}"
	else
		sport=""
		dport=""
	fi

	if [ "$type" = "1" ]; then
		###lan forward
		mark_ids=$((STREAM_IPPORT_LANID+id))
		auto_get_id=$(awk 'END{print $1+1,'$id'>>"/tmp/iktmp/ipt_rule_id/stream_ipport_id";print $1+1}' /tmp/iktmp/ipt_rule_id/stream_ipport_id 2>/dev/null)
		connmark_id=$((IPT_CONNMARK_STREAM_IPPORT+auto_get_id))
		connmark_ids="${connmark_id}"
		ip rule add from all fwmark $mark_ids table $mark_ids prio 15000
		local route_cmd="ip route add default via $nexthop table $mark_ids"
		$route_cmd
		route_rule_insert stream_ipport "$id $route_cmd"
		local IFNAMES=""
		local BAND_FLAGS=""
		local MODE_FLAGS=""
	else
		#循环加载规则 读取CONNMARK ID
		local iface_count=0
		local single_mark_id=
		for iface in ${interface//,/ };do
			mark_id=$(iproute_get_markid $iface)
			__wg_stream_ensure_iface_route "$iface" "$mark_id"
			__wg_stream_ensure_nat "$iface"
			iface_count=$((iface_count+1))
			single_mark_id="$mark_id"
			auto_get_id=$(awk 'END{print $1+1,'$id'>>"/tmp/iktmp/ipt_rule_id/stream_ipport_id";print $1+1}' /tmp/iktmp/ipt_rule_id/stream_ipport_id 2>/dev/null)
			connmark_id=$((IPT_CONNMARK_STREAM_IPPORT+auto_get_id))
			connmark_ids="${connmark_ids:+$connmark_ids,}${connmark_id}"
			mark_ids="${mark_ids:+$mark_ids,}${mark_id}"
			echo $id $IPTABLES_RULE_ALL -m connmark --mark $connmark_id $COMMENT -j MARK --set-mark $mark_id >>/tmp/iktmp/ipt_rule_id/stream_ipport_id_rule
		done
		if [ "$iface_count" = "1" -a "$single_mark_id" ]; then
			echo $id $IPTABLES_RULE_NEW $src $dst $PROTO $sport $dport $COMMENT $ipt_time -j MARK --set-mark $single_mark_id >>/tmp/iktmp/ipt_rule_id/stream_ipport_id_rule
			__wg_stream_preroute_add_mark "$single_mark_id"
		fi
		local IFNAMES="--set-ifname $interface"
		local BAND_FLAGS="--set-band-flag ${iface_band:-0}"
		local MODE_FLAGS="--set-mode ${mode:-0}"
	fi

	ik_cntl new_tc mark_rule add id $((IPT_CONNMARK_STREAM_IPPORT+id)) connmark ${connmark_ids} skbmark ${mark_ids} >/dev/null
	echo $id $IPTABLES_RULE_NEW $src $dst $PROTO $sport $dport $COMMENT $ipt_time -j NTH_CONNMARK --set-mark ${connmark_ids} $IFNAMES $BAND_FLAGS $MODE_FLAGS >>/tmp/iktmp/ipt_rule_id/stream_ipport_id_rule
}
__exec_rule_del() {
	local ipt_time=$(ipt_format_time "$week" "$time")
	
	sed -i -r "/^[0-9]+ (${id//,/|})$/d" /tmp/iktmp/ipt_rule_id/stream_ipport_id
	sed -i -r "/^(${id//,/|}) /d" /tmp/iktmp/ipt_rule_id/stream_ipport_id_rule
	line_num=`iptables -w -t mangle -L STREAM_IPPORT_NEW -n --line-numbers |awk '$0~/\/\* ('${id//,/|}') \*\//{print $1}'`
	num=0
	for line in $line_num ;do
		iptables -w -t mangle -D STREAM_IPPORT_NEW  $ipt_time $((line-$((num++)))) 2>/dev/null
	done

	for i in ${id//,/ };do
		ik_cntl new_tc mark_rule del id $((IPT_CONNMARK_STREAM_IPPORT+i)) >/dev/null
	done

	if [ "$type" = "1" ]; then
		local mark_ids=$((STREAM_IPPORT_LANID+id))
		ip route del default via $nexthop table $mark_ids
		ip rule del from all fwmark $mark_ids table $mark_ids
	fi
}
__format_ipset() {
	if [ "$1" = "src" ] ;then
		[ -n "$src_addr" ]&&{
			#循环判断地址类型（普通IP/群组名称）
			ipset_rule_add sipport_src_$id $src_addr
			echo "-m set --match-set sipport_src_$id src"
		}
	elif [ "$1" = "dst" ] ;then
		[ -n "$dst_addr" ]&&{
			ipset_rule_add sipport_dst_$id $dst_addr
			echo "-m set --match-set sipport_dst_$id dst"
		}
	fi
}
init() {
	iptables -w -t mangle -F STREAM_IPPORT_NEW
	iptables -w -t mangle -F STREAM_IPPORT_ALL
	$LOCKUP
	route_rule_clean stream_ipport
	__exec_rule_clean
	sql_config_get_list $IK_DB_CONFIG "select * from stream_ipport" |\
	while read config ;do
		sport= dport= src= dst= connmark_ids= PROTO=
		[ -n "$config" ]&&{
			local $config
			src=$(__format_ipset src)
			dst=$(__format_ipset dst)
			[ "$enabled" = "yes" ]&& {
				__exec_rule_add >/dev/null 2>/dev/null
			}
		}
	done
	__exec_rule_commit >/dev/null 2>/dev/null
	route_rule_commit
	$UNLOCK
}

vrrp_init()
{
	__clean
	sqlite3 $IK_DB_CONFIG "delete from stream_ipport"	
	sqlite3 $IK_DIR_LOG/vrrp/conf/config.db ".dump stream_ipport" |grep "^INSERT"| sqlite3 $IK_DB_CONFIG
	init
}

add() {
	__check_param || exit 1
	__check_interface_nums || exit 1
	sport= dport= src= dst= connmark_ids= PROTO=
	local sql_param="id:null enabled:str comment:str type:str nexthop:str interface:str mode:int iface_band:int src_addr:str dst_addr:str protocol:str src_port:str dst_port:str week:str time:str"
	if SqlMsg=$(sql_config_insert $IK_DB_CONFIG stream_ipport $sql_param);then
		local id=$SqlMsg
		src=$(__format_ipset src)
		dst=$(__format_ipset dst)
		[ "$enabled" = "yes" ]&& {
			$LOCKUP
			__exec_rule_add >/dev/null 2>/dev/null
			__exec_rule_commit >/dev/null 2>/dev/null
			$UNLOCK
		}
		route_rule_commit
		echo "$SqlMsg"
		return 0
	else
		echo "$SqlMsg"
		return 1
	fi
}

del() {
	sql_config_get_list $IK_DB_CONFIG "select * from stream_ipport where id in ($id); delete from stream_ipport where id in ($id);" | \
	while read config; do
		local $config
		$LOCKUP
		__exec_rule_del >/dev/null 2>/dev/null
		$UNLOCK
		for ID in ${id//,/ };do
			ipset_rule_del sipport_src_$ID
			ipset_rule_del sipport_dst_$ID
		done
	done
	route_rule_delete stream_ipport "$id"
	route_rule_commit
}

down() {
	sql_config_get_list $IK_DB_CONFIG "select * from stream_ipport where id in ($id) and enabled='yes'; update stream_ipport set enabled='no' where id in ($id) ;" | \
	while read config; do
		local $config
		$LOCKUP
		__exec_rule_del >/dev/null 2>/dev/null
		$UNLOCK
	done
	route_rule_delete stream_ipport "$id"
	route_rule_commit
}

up() {
	sql_config_get_list $IK_DB_CONFIG "select * from stream_ipport where id in ($id) and enabled='no';update stream_ipport set enabled='yes' where id in ($id);"|while read config ;do
		sport= dport= src= dst= connmark_ids= PROTO=
		local $config 
		[ -n "$src_addr" ]&&src="-m set --match-set sipport_src_$id src"
		[ -n "$dst_addr" ]&&dst="-m set --match-set sipport_dst_$id dst"
		$LOCKUP
		__exec_rule_add >/dev/null 2>/dev/null
		$UNLOCK
	done
	__exec_rule_commit >/dev/null 2>/dev/null
	route_rule_commit
}

edit() {
	__check_param || exit 1
	__check_interface_nums || exit 1
	local sql_param="enabled:str comment:str type:str nexthop:str interface:str mode:int iface_band:int src_addr:str dst_addr:str protocol:str src_port:str dst_port:str week:str time:str"
	res=$(sql_config_get_list $IK_DB_CONFIG "select * from stream_ipport where id=$id" prefix=old_)
	if [ "$res" = "" ];then
		return 0
	fi
	local $res
	if SqlMsg=$(sql_config_update $IK_DB_CONFIG stream_ipport "id=$id" $sql_param);then
		if ! NewOldVarl type nexthop interface mode iface_band src_addr dst_addr protocol src_port dst_port week time; then
			src=$(__format_ipset src)
			dst=$(__format_ipset dst)
			[ "$enabled" = "yes" ]&&{
				$LOCKUP
				type=$old_type nexthop=$old_nexthop __exec_rule_del >/dev/null 2>/dev/null
				route_rule_delete stream_ipport "$id"
				__exec_rule_add >/dev/null 2>/dev/null
				__exec_rule_commit >/dev/null 2>/dev/null
				route_rule_commit
				$UNLOCK
			}
		fi
		return 0
	else
		echo "$SqlMsg"
		return 1
	fi
}
__clean() {
	$LOCKUP
	sql_config_get_list $IK_DB_CONFIG "select * from stream_ipport;" |\
	while read config; do
		local $config
		__exec_rule_del >/dev/null 2>/dev/null
		ipset_rule_del sipport_src_$id
		ipset_rule_del sipport_dst_$id
	done
	$UNLOCK
	route_rule_clean stream_ipport
	route_rule_commit
}

EXPORT() {
	Include import_export.sh
	local format=${format:-txt}
	if errmsg=$(export_txt $IK_DB_CONFIG stream_ipport $format $IK_DIR_EXPORT/stream_ipport.$format) ;then
		echo "stream_ipport.$format"
		return 0
	else
		echo "$errmsg"
		return 1
	fi
}

IMPORT() {
	Include import_export.sh
	if errmsg=$(import_txt $IK_DB_CONFIG stream_ipport $IK_DIR_IMPORT/$filename "$append"  __check_param __clean) ;then
		init >/dev/null 2>/dev/null &
		return 0
	else
		echo "$errmsg"
		return 1
	fi
}
show()
{
	local __filter=$(sql_auto_get_filter)
	local __order=$(sql_auto_get_order)
	local __limit=$(sql_auto_get_limit)
	local __where="$__filter $__order $__limit"
	Show __json_result__
}
__show_total()
{
	local total=$(sqlite3 $IK_DB_CONFIG "select count() from stream_ipport $__filter")
	json_append __json_result__ total:int
}
__show_data()
{
	local sql_show="select * from stream_ipport $__where"
	local data=$(sql_config_get_json $IK_DB_CONFIG "$sql_show")
	json_append __json_result__ data:json
	return 0;
}
__show_interface()
{
	__wg_stream_cache_update
	local interface=$(interface_get_ifname_comment_json wan,vpn,sdwan,sdsaas -sdwan)
	if [ "$interface" = "" -o "$interface" = "[]" ]; then
		local wan_items
		wan_items=$(interface_get_ifname wan 2>/dev/null | awk 'NF{printf "%s[\\\"%s\\\"]", sep, $1; sep=","}')
		[ "$wan_items" ] && interface="[$wan_items]"
	fi
	interface=$(__wg_stream_append_interface_json "$interface")
	json_append __json_result__ interface:json
}
__show_protocol()
{
	local protocol="[\"tcp\",\"udp\",\"tcp+udp\",\"icmp\",\"any\"]"
	json_append __json_result__ protocol:json
}
__show_ipgroup()
{
	local ipgroup=$(ipgroup_get_groupname_json)
	json_append __json_result__ ipgroup:json
}

__show_macgroup()
{
        local macgroup=$(macgroup_get_groupname_json)
        json_append __json_result__ macgroup:json
}

__show_dtgroup()
{
        local dtgroup=$(dtgroup_get_groupname_json)
        json_append __json_result__ dtgroup:json
}
